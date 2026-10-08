# AGENTS.md

Guía para agentes de IA (y humanos) que trabajen en esta microapp Django de **agenda de citas**. Lee también `README.md` para las reglas de negocio completas.

## Resumen del proyecto

Microapp Django + DRF que gestiona citas: apertura/cierre por día, cupos, asignación automática de personal, lista de espera, cancelación y reprogramación, y horarios configurables por trabajador.

## Comandos

El proyecto usa **uv**. Todos los comandos se ejecutan con `uv run` (no activar venv manualmente, no usar `pip`).

```bash
uv sync                                          # instalar dependencias desde uv.lock
uv run python manage.py runserver                # desarrollo
uv run python manage.py makemigrations && uv run python manage.py migrate
uv run pytest                                    # todos los tests
uv run pytest agenda/tests/test_capacity.py -k nombre   # un test
uv run ruff check . --fix && uv run ruff format .       # lint y formato
uv run celery -A config worker -l info           # worker de Celery
uv run celery -A config beat -l info             # Celery beat scheduler
uv run python manage.py process_waitlist         # procesar lista de espera
uv run python manage.py expire_waitlist          # expirar citas vencidas en espera
uv add <paquete>                                 # dependencia de producción
uv add --dev <paquete>                           # dependencia de desarrollo
```

Antes de dar una tarea por terminada deben pasar `uv run pytest` y `uv run ruff check .`.

## Arquitectura

Capas (dependencias solo hacia abajo):

```
api (views/serializers) → services / selectors → models
```

- **`models/`**: campos, constraints, validaciones simples. Sin lógica de casos de uso.
- **`services/`**: **toda** la lógica de negocio (reservar, asignar, cancelar, reprogramar, procesar lista de espera, expirar, cambiar horarios). Funciones con tipos, que reciben datos primitivos/instancias y lanzan excepciones de dominio.
- **`selectors/`**: consultas de solo lectura (disponibilidad, agenda del día, lista de espera). No modifican datos.
- **`api/`**: serializers y viewsets delgados; validan formato, llaman a un service y traducen excepciones de dominio a HTTP. **Prohibido** poner reglas de negocio aquí.
- **`tasks.py`**: Celery; solo llama a services.
- **Admin**: los modelos de catálogo editados en admin (`Worker`, `WorkSchedule`, `ScheduleException`, `DayConfig`) usan `WaitlistTriggerMixin` para llamar a `schedule_waitlist_processing()` vía `transaction.on_commit`. El admin solo orquesta y no contiene lógica de negocio.

Excepciones de dominio en `agenda/exceptions.py` (`DayClosed`, `QuotaExceeded`, `NoWorkerAvailable`, `CancellationNotAllowed`, `RescheduleLimitReached`, …).

## Reglas de dominio (no romper)

1. **Duración de servicio ≤ 60 min**, configurable por servicio (validar en modelo y serializer).
2. **Cupo efectivo del día** = `min(DayConfig.max_appointments, capacidad_personal)`. `max_appointments` nulo = solo capacidad del personal. La función única es `services/capacity.py`; no recalcular en otro lado.
3. **Capacidad del trabajador**: una cita no puede cruzar el descanso. La capacidad es la suma, por tramo continuo de trabajo, de `floor(minutos_del_tramo / duración)`. `services/capacity.py` es la única fuente de este cálculo y es puro (sin BD). Las excepciones por fecha (`ScheduleException`) prevalecen sobre el horario semanal. Día con `is_open=False` → no se agenda.
4. **Asignación**: trabajador activo, dentro de horario, sin traslape; se elige el de menor carga del día (desempate por id). Sin trabajador libre → estado `EN_ESPERA`, nunca error al usuario (salvo tope de espera).
5. **Lista de espera FIFO**: se reevalúa al cancelar, reprogramar, cambiar horarios, agregar/activar personal o reabrir un día. Subir el cupo **no** promueve citas porque `WAITLISTED` ya consumió cupo en su solicitud inicial. Hay un único punto de entrada: `services/waitlist.py::process_waitlist(date)`. Prohibido reimplementar la asignación en otros módulos.
6. **FIFO sin bloqueo de cabecera:** se procesa por `created_at, id`. Si la primera cita en espera no cabe en su horario solicitado, no bloquea a las siguientes que soliciten otros horarios libres.
7. **Reprogramar** = crear la nueva cita pasando todas las validaciones y, solo si tiene éxito, marcar la anterior como `REPROGRAMADA` con `rescheduled_to`. Todo en una sola transacción.
8. **Cancelar/reprogramar** respeta `CANCEL_MIN_HOURS` y `MAX_RESCHEDULES_PER_APPOINTMENT`.
9. **Cambio de horario del personal:** `revalidate_worker(worker_id, ...)` en `agenda/services/schedules.py` es el único punto de entrada para revalidar, desplazar y reasignar citas tras cambios de turno, excepciones o estado activo. Las citas desplazadas se intentan reasignar a otro trabajador libre con `reassign_worker()` o pasan a `WAITLISTED` con `transition(..., via_revalidation=True)` conservando su `created_at` original e ignorando `WAITLIST_MAX_PER_DAY`. Ninguna cita confirmada se cancela automáticamente.
10. Cada cambio de estado escribe un `AppointmentEvent` (auditoría). No cambiar `status` ni `worker` directamente; usar services.

## Concurrencia e integridad

- **Serialización por día:** Reservar y asignar dentro de `transaction.atomic()` tomando locks consultivos de PostgreSQL `pg_advisory_xact_lock(42, date.toordinal())` (helper centralizado en `agenda/services/locks.py`). Al operar sobre múltiples fechas (reprogramación o cambios de horario), los locks **siempre se adquieren en orden cronológico ascendente** (`day_advisory_locks`) para evitar interbloqueos.
- **Red de seguridad en BD:** `ExclusionConstraint` de PostgreSQL (`tstzrange(start_at, end_at) &&` sobre `worker`) con `BtreeGistExtension` para impedir citas solapadas con trabajador asignado (`OCCUPYING_STATUSES`).
- **El `status` y `worker` solo cambian desde services:** Nunca mutar `status` o `worker` directamente en admin, vistas o señales. Cada transición escribe un `AppointmentEvent`.
- **Ubicación de lógica clave:**
  - Estados y conjuntos (`QUOTA_STATUSES`, `OCCUPYING_STATUSES`, `ACTIVE_STATUSES`): en `agenda/constants.py`.
  - Asignación pura de personal (`pick_worker`): en `agenda/services/assignment.py`.
  - Reasignación y expiración de lista de espera (`process_waitlist`, `expire_waitlist`): en `agenda/services/waitlist.py`.
  - Revalidación por cambio de horario (`revalidate_worker`, `revalidate_all`): en `agenda/services/schedules.py`.
  - Locks por día (`day_advisory_lock`, `day_advisory_locks`): en `agenda/services/locks.py`.
  - Identificación y normalización de solicitante (`get_or_create_requester`, `normalize_phone`): en `agenda/services/requesters.py`.
- Constraints en BD cuando sea posible (únicos, checks de rango horario `start < end`).
- Operaciones idempotentes en tareas Celery.

## Autenticación, permisos y seguridad (Fase 7a)

- **Denegar por defecto:** La API tiene `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`. Toda vista nueva **debe declarar explícitamente sus permisos**. Las únicas vistas públicas declaran `permission_classes = [AllowAny]` y están registradas en la lista blanca `PUBLIC_ENDPOINTS_WHITELIST` (`agenda/api/permissions.py`), verificada automáticamente en tests.
- **Roles efectivos (`agenda/api/roles.py`):**
  - `STAFF`: `user.is_staff=True` o `user.is_superuser=True`. Control total.
  - `WORKER`: `Worker.user` vinculado y `Worker.is_active=True`. Solo sus propios recursos.
  - `NONE`: Usuario autenticado sin rol. Recibe `403 Forbidden` en endpoints protegidos.
- **Permisos reutilizables (`agenda/api/permissions.py`):**
  - `IsStaff`, `IsWorker`, `IsWorkerSelfOrStaff`, `IsAppointmentWorkerOrStaff`, `HasManageTokenOrStaff`.
- **Token de gestión (`manage_token`):**
  - Generado con `secrets.token_urlsafe(32)`.
  - Solo se persiste su hash SHA-256 (`manage_token_hash`).
  - **Nunca registrar en logs** (`logger`, `caplog`) ni devolver fuera de la respuesta directa de creación (`POST /appointments/`), reprogramación o rotación por staff (`POST /appointments/{id}/token/`).
  - Sin token válido o con token incorrecto, las operaciones del solicitante devuelven **404 Not Found** (`APPOINTMENT_NOT_FOUND`) para prevenir enumeración.
- **Protección de login:** Bloqueo tras 5 intentos fallidos (`LOGIN_MAX_FAILED_ATTEMPTS`) durante 15 min (`LOGIN_LOCKOUT_MINUTES`) en caché Redis/LocMem, respondiendo `429 LOGIN_LOCKED`. Mensaje uniforme `INVALID_CREDENTIALS` (401) para usuarios existentes o no.

## Matriz de permisos (Fase 7a)

| Acción / Endpoint | Público | Solicitante (`X-Manage-Token`) | Trabajador (`WORKER`) | Staff (`STAFF`) |
|---|---|---|---|---|
| `GET /api/v1/health/` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/v1/availability/` | ✅ | ✅ | ✅ | ✅ |
| `POST /api/v1/appointments/` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/v1/appointments/{id}/` | ❌ (401/404) | ✅ Su cita | ✅ Solo sus citas asignadas | ✅ Todas |
| `POST /api/v1/appointments/{id}/cancel/` | ❌ (401/404) | ✅ Su cita | ❌ (403) | ✅ (con `force`) |
| `POST /api/v1/appointments/{id}/reschedule/` | ❌ (401/404) | ✅ Su cita | ❌ (403) | ✅ (con `force`) |
| `POST /api/v1/appointments/{id}/complete/` | ❌ (401/404) | ❌ (403/404) | ✅ Solo sus citas asignadas | ✅ |
| `POST /api/v1/appointments/{id}/no-show/` | ❌ (401/404) | ❌ (403/404) | ✅ Solo sus citas asignadas | ✅ |
| `POST /api/v1/appointments/{id}/token/` | ❌ (401) | ❌ (403) | ❌ (403) | ✅ |
| `GET /api/v1/appointments/` (`?unserviceable=true`) | ❌ (401) | ❌ (403) | ❌ (403) | ✅ |
| `GET /api/v1/waitlist/` | ❌ (401) | ❌ (403) | ❌ (403) | ✅ |
| `GET /api/v1/me/agenda/?date=` | ❌ (401) | ❌ (403) | ✅ Su propia agenda | ✅ Con `worker_id` |
| `GET/PUT /api/v1/workers/{id}/schedule/` | ❌ (401) | ❌ (403) | ✅ Solo su propio perfil | ✅ |
| `POST/DELETE /api/v1/workers/{id}/exceptions/`| ❌ (401) | ❌ (403) | ✅ Solo su propio perfil | ✅ |
| `PATCH /api/v1/workers/{id}/` (`is_active`) | ❌ (401) | ❌ (403) | ❌ (403) | ✅ |
| `GET/PUT /api/v1/day-configs/...` | ❌ (401) | ❌ (403) | ❌ (403) | ✅ |
| `POST /api/v1/auth/token/` | ✅ | ✅ | ✅ | ✅ |
| `POST /api/v1/auth/token/refresh/` | ✅ | ✅ | ✅ | ✅ |
| `POST /api/v1/auth/logout/` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/v1/auth/me/` | ❌ (401) | ❌ (401) | ✅ | ✅ |

## Fechas y horas

- `USE_TZ = True`, zona `America/Mexico_City`.
- Guardar `datetime` aware (UTC en BD); comparar/mostrar en zona local.
- Para horarios del personal usar `TimeField` + día de la semana (0 = lunes). Nunca mezclar naive y aware.
- En tests, congelar el tiempo (`freezegun` o `time-machine`).

## Convenciones de código

- Python tipado, `ruff` como linter/formateador, líneas ≤ 100.
- Nombres de código en inglés; textos al usuario y docs en español.
- Services: una función por caso de uso, nombre verbo (`book_appointment`, `cancel_appointment`).
- No usar `signals` para lógica de negocio. No lógica en `save()` ni en `admin.py`.
- Evitar N+1: `select_related` / `prefetch_related` en selectors.
- API versionada bajo `/api/v1/`. Errores con formato `{"code": "...", "detail": "..."}`.

## Tests y fábricas

- `pytest` + `pytest-django`; fábricas con `factory_boy` (`agenda/tests/factories.py`):
  - `StaffUserFactory`: crea usuario con `is_staff=True`.
  - `WorkerUserFactory`: crea usuario y modelo `Worker` vinculado y activo.
  - `SuperUserFactory`: crea superusuario.
  - `create_appointment_with_token(service, requester, start_at, ...)`: helper que genera la cita y devuelve `(appointment, raw_token)`.
- Fixtures en `conftest.py`: `auth_client_staff`, `auth_client_worker`, `jwt_token_for(user)`.
- Todo service nuevo o modificado requiere tests de: caso feliz, cada excepción de dominio y bordes (cupo exacto, última hora del turno, cambio de día).
- Ubicación: `agenda/tests/test_<modulo>.py`.

## Qué NO hacer

- No editar ni borrar migraciones ya aplicadas; crear nuevas.
- No agregar dependencias sin justificarlo en el PR/commit; siempre con `uv add` y commitear `pyproject.toml` + `uv.lock`.
- No usar `pip install` ni `requirements.txt`; no editar `uv.lock` a mano.
- No hardcodear límites: viven en `settings` o en `DayConfig`.
- No borrar citas físicamente; usar estados.
- No exponer datos personales del solicitante ni tokens en logs.
- No modificar el esquema de la API pública sin actualizar `README.md`.

## Flujo de trabajo para el agente

1. Leer `README.md` y esta guía; ubicar el service afectado.
2. Escribir/ajustar tests primero cuando se trate de una regla de negocio.
3. Implementar en `services/` (no en vistas).
4. Generar migración si cambian modelos y revisarla.
5. Ejecutar `uv run pytest` y `uv run ruff check .`.
6. Actualizar `README.md` si cambian reglas, endpoints o variables de configuración.

## Definición de terminado

- [ ] Tests nuevos y existentes pasan
- [ ] `ruff check` y `ruff format --check` limpios
- [ ] Migraciones incluidas y revisadas
- [ ] Reglas de dominio respetadas (sección anterior)
- [ ] Documentación actualizada