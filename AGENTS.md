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
- **`services/`**: **toda** la lógica de negocio (reservar, asignar, cancelar, reprogramar, cambiar horarios). Funciones con tipos, que reciben datos primitivos/instancias y lanzan excepciones de dominio.
- **`selectors/`**: consultas de solo lectura (disponibilidad, agenda del día). No modifican datos.
- **`api/`**: serializers y viewsets delgados; validan formato, llaman a un service y traducen excepciones de dominio a HTTP. **Prohibido** poner reglas de negocio aquí.
- **`tasks.py`**: Celery; solo llama a services.

Excepciones de dominio en `agenda/exceptions.py` (`DayClosed`, `QuotaExceeded`, `NoWorkerAvailable`, `CancellationNotAllowed`, `RescheduleLimitReached`, …).

## Reglas de dominio (no romper)

1. **Duración de servicio ≤ 60 min**, configurable por servicio (validar en modelo y serializer).
2. **Cupo efectivo del día** = `min(DayConfig.max_appointments, capacidad_personal)`. `max_appointments` nulo = solo capacidad del personal. La función única es `services/capacity.py`; no recalcular en otro lado.
3. **Capacidad del trabajador**: una cita no puede cruzar el descanso. La capacidad es la suma, por tramo continuo de trabajo, de `floor(minutos_del_tramo / duración)`. `services/capacity.py` es la única fuente de este cálculo y es puro (sin BD). Las excepciones por fecha (`ScheduleException`) prevalecen sobre el horario semanal. Día con `is_open=False` → no se agenda.
4. **Asignación**: trabajador activo, dentro de horario, sin traslape; se elige el de menor carga del día (desempate por id). Sin trabajador libre → estado `EN_ESPERA`, nunca error al usuario (salvo tope de espera).
5. **Lista de espera FIFO**: se reevalúa al cancelar, reprogramar, cambiar horarios, agregar personal o subir cupo. Hay un único punto de entrada: `assignment.process_waitlist(date)`.
6. **Reprogramar** = crear la nueva cita pasando todas las validaciones y, solo si tiene éxito, marcar la anterior como `REPROGRAMADA` con `rescheduled_to`. Todo en una sola transacción.
7. **Cancelar/reprogramar** respeta `CANCEL_MIN_HOURS` y `MAX_RESCHEDULES_PER_APPOINTMENT`.
8. **Cambio de horario de un trabajador** revalida sus citas futuras: las que ya no caben se desasignan y pasan por asignación/espera.
9. Cada cambio de estado escribe un `AppointmentEvent` (auditoría). No cambiar `status` directamente; usar services.

## Concurrencia e integridad

- **Serialización por día:** Reservar y asignar dentro de `transaction.atomic()` tomando un lock consultivo de PostgreSQL `pg_advisory_xact_lock(42, date.toordinal())` (o `select_for_update()` sobre configuración/trabajadores). Esto serializa reservas por día sin requerir filas preexistentes de `DayConfig`.
- **Red de seguridad en BD:** `ExclusionConstraint` de PostgreSQL (`tstzrange(start_at, end_at) &&` sobre `worker`) con `BtreeGistExtension` para impedir citas solapadas con trabajador asignado (`OCCUPYING_STATUSES`).
- **El `status` solo cambia desde services:** Nunca mutar `status` o `worker` directamente en admin, vistas o señales. Cada transición escribe un `AppointmentEvent`.
- **Ubicación de lógica clave:**
  - Estados y conjuntos (`QUOTA_STATUSES`, `OCCUPYING_STATUSES`, `ACTIVE_STATUSES`): en `agenda/constants.py`.
  - Asignación pura de personal (`pick_worker`): en `agenda/services/assignment.py`.
  - Identificación y normalización de solicitante (`get_or_create_requester`, `normalize_phone`): en `agenda/services/requesters.py`.
- Constraints en BD cuando sea posible (únicos, checks de rango horario `start < end`).
- Operaciones idempotentes en tareas Celery.

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

## Tests

- `pytest` + `pytest-django`; fábricas con `factory_boy`.
- Todo service nuevo o modificado requiere tests de: caso feliz, cada excepción de dominio y bordes (cupo exacto, última hora del turno, cambio de día).
- Obligatorios: carrera por el último cupo (dos solicitudes concurrentes), espera → asignación FIFO tras cancelación, revalidación tras cambio de horario, reprogramación fallida conserva la cita original.
- Ubicación: `agenda/tests/test_<modulo>.py`.

## Qué NO hacer

- No editar ni borrar migraciones ya aplicadas; crear nuevas.
- No agregar dependencias sin justificarlo en el PR/commit; siempre con `uv add` y commitear `pyproject.toml` + `uv.lock`.
- No usar `pip install` ni `requirements.txt`; no editar `uv.lock` a mano.
- No hardcodear límites: viven en `settings` o en `DayConfig`.
- No borrar citas físicamente; usar estados.
- No exponer datos personales del solicitante en logs.
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