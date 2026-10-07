# Agenda de Citas (microapp Django)

Microapp para gestionar citas: apertura y cierre de agenda, cupos por día, asignación automática de personal, lista de espera, cancelación y reposición de fechas.

## Stack

- Python 3.12+, Django 5.x, Django REST Framework
- Gestión de entorno y dependencias: [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`)
- PostgreSQL (SQLite solo para desarrollo)
- Celery + Redis (opcional: reasignación de espera, recordatorios)
- pytest + pytest-django, ruff
- Zona horaria: `America/Mexico_City`

## Conceptos clave

| Concepto | Descripción |
|---|---|
| **Solicitante** | Persona que pide la cita (nombre, teléfono, correo). |
| **Servicio** | Tipo de cita con duración en minutos (**≤ 60**, configurable). |
| **Trabajador** | Personal que atiende. Tiene horario propio por día de la semana. |
| **Horario laboral** | Entrada, salida y descanso opcional por trabajador y día. |
| **Excepción de horario** | Ausencia, vacaciones o horario especial en una fecha concreta. |
| **Configuración de día** | Cupo máximo de citas y estado abierto/cerrado, por día de la semana (default) o por fecha (override). |
| **Cita** | Solicitante + servicio + fecha/hora + trabajador (puede ser nulo si está en espera). |
| **Lista de espera** | Citas sin trabajador disponible; se asignan por orden de llegada (FIFO). |

## Estados de la cita

```
SOLICITADA ──asignación──► CONFIRMADA ──► COMPLETADA
    │                          │
    │ (sin personal)           ├──► CANCELADA
    ▼                          ├──► NO_ASISTIO
  EN_ESPERA ──(se libera)──►   └──► REPROGRAMADA (enlaza a la nueva cita)
    │
    └──► CANCELADA / EXPIRADA
```

## Reglas de negocio

### 1. Apertura y cierre
- Cada día puede estar **abierto** o **cerrado** (`DayConfig.is_open`).
- Ventana de reserva: `BOOKING_MIN_ADVANCE_HOURS` (anticipación mínima) y `BOOKING_MAX_ADVANCE_DAYS` (máximo a futuro).
- Cerrar un día con citas existentes **no las borra**: se listan para reprogramar o cancelar.

### 2. Duración y capacidad
- La duración la define el servicio (`duration_minutes`, 5–60).
- Capacidad por trabajador en un día:

```
capacidad_trabajador = floor((salida - entrada - descansos) / duración)
capacidad_personal   = Σ capacidad_trabajador   (solo trabajadores activos y sin excepción)
cupo_efectivo        = min(DayConfig.max_appointments, capacidad_personal)
```

- Si `max_appointments` es nulo, solo aplica la capacidad del personal.
- Una cita se acepta solo si `citas_activas_del_día < cupo_efectivo`.

### 3. Asignación de personal
1. Se buscan trabajadores activos cuyo horario cubra `[inicio, fin)` y sin cita traslapada.
2. Se elige al de **menor carga del día** (desempate: el de menor id).
3. Si ninguno está libre → la cita queda `EN_ESPERA` (si no excede `WAITLIST_MAX_PER_DAY`).
4. La asignación corre dentro de `transaction.atomic()` con `select_for_update()` para evitar doble reserva.

### 4. Lista de espera
- Se reevalúa (FIFO) cuando: se cancela una cita, cambia un horario, se agrega personal o se aumenta el cupo.
- Las citas en espera expiran si llega la fecha sin asignarse (`EXPIRADA`).

### 5. Cancelación y reposición
- Solo se puede cancelar/reprogramar con `CANCEL_MIN_HOURS` de anticipación (configurable).
- Máximo `MAX_RESCHEDULES_PER_APPOINTMENT` reprogramaciones por cita.
- Reprogramar = crear nueva cita (pasa por las mismas validaciones) + marcar la anterior `REPROGRAMADA` con `rescheduled_to`. Si la nueva falla, la anterior se conserva.
- Todo cambio de estado queda en `AppointmentEvent` (auditoría).

### 6. Límites adicionales
- Máx. citas activas por solicitante por día: `MAX_ACTIVE_PER_REQUESTER_PER_DAY`.
- Sin traslape de citas del mismo solicitante.

### 7. Horarios del personal
- Se configuran por día de la semana (entrada, salida, descanso).
- Cambiar un horario **revalida** las citas futuras del trabajador: las que ya no caben se desasignan y vuelven a asignación/espera.
- Las excepciones por fecha tienen prioridad sobre el horario semanal.

## Estructura del proyecto

```
agenda/
├── models/            # Requester, Service, Worker, WorkSchedule, ScheduleException,
│                      # DayConfig, Appointment, AppointmentEvent
├── services/          # Casos de uso (toda la lógica de negocio)
│   ├── booking.py         # solicitar, confirmar
│   ├── assignment.py      # elegir trabajador, lista de espera
│   ├── capacity.py        # cálculo de cupos y disponibilidad
│   ├── cancellation.py    # cancelar, reprogramar
│   └── schedules.py       # cambios de horario y revalidación
├── selectors/         # Consultas de solo lectura (disponibilidad, agenda del día)
├── api/               # serializers, viewsets, urls (sin lógica de negocio)
├── tasks.py           # Celery: reasignar espera, expirar, recordatorios
├── admin.py
├── tests/
└── migrations/
```

## API (v1)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/availability/?date=&service=` | Horarios libres y cupo restante |
| POST | `/api/v1/appointments/` | Solicitar cita (confirma o deja en espera) |
| GET | `/api/v1/appointments/{id}/` | Detalle |
| POST | `/api/v1/appointments/{id}/cancel/` | Cancelar |
| POST | `/api/v1/appointments/{id}/reschedule/` | Reprogramar |
| GET/PUT | `/api/v1/day-configs/{date}/` | Cupo y apertura/cierre del día |
| GET/PUT | `/api/v1/workers/{id}/schedule/` | Horario del trabajador |
| POST | `/api/v1/workers/{id}/exceptions/` | Ausencia o día especial |
| GET | `/api/v1/waitlist/?date=` | Citas en espera |

## Configuración (`settings` / variables de entorno)

| Variable | Default | Descripción |
|---|---|---|
| `BOOKING_MIN_ADVANCE_HOURS` | 2 | Anticipación mínima para agendar |
| `BOOKING_MAX_ADVANCE_DAYS` | 60 | Máximo de días a futuro |
| `CANCEL_MIN_HOURS` | 4 | Anticipación mínima para cancelar/reprogramar |
| `MAX_RESCHEDULES_PER_APPOINTMENT` | 2 | Reprogramaciones permitidas |
| `MAX_ACTIVE_PER_REQUESTER_PER_DAY` | 1 | Citas activas por solicitante/día |
| `WAITLIST_MAX_PER_DAY` | 20 | Tope de espera por día |
| `DEFAULT_SLOT_STEP_MINUTES` | 15 | Granularidad de horarios ofrecidos |

## Puesta en marcha

### Crear el proyecto desde cero

```bash
uv init agenda-citas --app && cd agenda-citas
uv add django djangorestframework psycopg[binary] python-decouple
uv add --dev pytest pytest-django factory-boy freezegun ruff
# opcional: uv add celery redis
uv run django-admin startproject config .
uv run python manage.py startapp agenda
```

### Clonar y ejecutar

```bash
uv sync                      # crea .venv e instala desde uv.lock
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

### Tests y calidad

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

> Dependencias: `uv add <paquete>` (o `uv add --dev <paquete>`). No usar `pip install` ni editar `uv.lock` a mano.

## Casos de prueba mínimos

- Cupo diario lleno → rechaza o manda a espera según configuración.
- Sin trabajadores libres → `EN_ESPERA`; al cancelar otra cita, se asigna FIFO.
- Dos solicitudes simultáneas al último cupo → solo una se confirma.
- Cambio de horario del trabajador → revalida citas futuras.
- Reprogramar falla → la cita original queda intacta.
- Duración > 60 min → error de validación.

## Roadmap

- Notificaciones (correo/WhatsApp) y recordatorios
- Múltiples sedes/recursos (consultorios)
- Servicios con trabajadores específicos (habilidades)
- Portal público para el solicitante