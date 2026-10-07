"""Management command to seed demo catalog data for development and testing."""

import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from agenda.models import (
    DayConfig,
    ExceptionKind,
    Requester,
    ScheduleException,
    Service,
    Weekday,
    Worker,
    WorkSchedule,
)


class Command(BaseCommand):
    """Seed initial catalog data (services, workers, schedules, day configs)."""

    help = "Populates database with sample demo data (only allowed when DEBUG=True)."

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("El comando seed_demo solo está permitido cuando DEBUG=True.")

        self.stdout.write("Poblando datos de demostración...")

        with transaction.atomic():
            # 1. Services
            services_data = [
                ("Consulta Rápida", "Atención rápida de trámites", 15),
                ("Consulta General", "Revisión general y diagnóstico", 30),
                ("Evaluación Completa", "Evaluación detallada y plan de acción", 60),
            ]
            for name, desc, duration in services_data:
                Service.objects.update_or_create(
                    name=name,
                    defaults={
                        "description": desc,
                        "duration_minutes": duration,
                        "is_active": True,
                    },
                )
            self.stdout.write(self.style.SUCCESS("✓ 3 Servicios creados / actualizados."))

            # 2. Workers
            workers_data = [
                ("Dra. Ana López", True),
                ("Dr. Carlos Ruiz", True),
                ("Lic. Elena Morales", True),
            ]
            workers: dict[str, Worker] = {}
            for name, is_active in workers_data:
                worker, _ = Worker.objects.update_or_create(
                    full_name=name,
                    defaults={"is_active": is_active},
                )
                workers[name] = worker
            self.stdout.write(self.style.SUCCESS("✓ 3 Trabajadores creados / actualizados."))

            # 3. Work Schedules (Monday to Friday)
            workdays = [
                Weekday.MONDAY,
                Weekday.TUESDAY,
                Weekday.WEDNESDAY,
                Weekday.THURSDAY,
                Weekday.FRIDAY,
            ]

            # Worker 1: 09:00 - 17:00, break 13:00 - 14:00
            w1 = workers["Dra. Ana López"]
            for day in workdays:
                WorkSchedule.objects.update_or_create(
                    worker=w1,
                    weekday=day,
                    defaults={
                        "start_time": datetime.time(9, 0),
                        "end_time": datetime.time(17, 0),
                        "break_start": datetime.time(13, 0),
                        "break_end": datetime.time(14, 0),
                    },
                )

            # Worker 2: 08:00 - 16:00, no break
            w2 = workers["Dr. Carlos Ruiz"]
            for day in workdays:
                WorkSchedule.objects.update_or_create(
                    worker=w2,
                    weekday=day,
                    defaults={
                        "start_time": datetime.time(8, 0),
                        "end_time": datetime.time(16, 0),
                        "break_start": None,
                        "break_end": None,
                    },
                )

            # Worker 3: 10:00 - 18:00, no break
            w3 = workers["Lic. Elena Morales"]
            for day in workdays:
                WorkSchedule.objects.update_or_create(
                    worker=w3,
                    weekday=day,
                    defaults={
                        "start_time": datetime.time(10, 0),
                        "end_time": datetime.time(18, 0),
                        "break_start": None,
                        "break_end": None,
                    },
                )
            self.stdout.write(self.style.SUCCESS("✓ Horarios laborales semanales configurados."))

            # 4. Day Config defaults
            # Monday - Friday: open, max 20 appointments
            for day in workdays:
                DayConfig.objects.update_or_create(
                    weekday=day,
                    defaults={
                        "is_open": True,
                        "max_appointments": 20,
                        "note": f"Horario regular de {Weekday(day).label}",
                    },
                )

            # Saturday & Sunday: closed, max 0
            weekend_days = [Weekday.SATURDAY, Weekday.SUNDAY]
            for day in weekend_days:
                DayConfig.objects.update_or_create(
                    weekday=day,
                    defaults={
                        "is_open": False,
                        "max_appointments": 0,
                        "note": f"Cerrado en fin de semana ({Weekday(day).label})",
                    },
                )
            self.stdout.write(self.style.SUCCESS("✓ Configuración semanal de días configurada."))

            # 5. Sample Schedule Exception (Worker 1 absence on upcoming date)
            today = timezone.localdate()
            sample_date = today + datetime.timedelta(days=7)
            ScheduleException.objects.update_or_create(
                worker=w1,
                date=sample_date,
                defaults={
                    "kind": ExceptionKind.ABSENCE,
                    "start_time": None,
                    "end_time": None,
                    "break_start": None,
                    "break_end": None,
                    "reason": "Permiso de capacitación médica",
                },
            )
            self.stdout.write(self.style.SUCCESS("✓ Excepción de horario de ejemplo creada."))

            # 6. Sample Requester
            Requester.objects.update_or_create(
                full_name="Juan Pérez Demo",
                defaults={
                    "email": "juan.perez@example.com",
                    "phone": "5551234567",
                },
            )

        self.stdout.write(self.style.SUCCESS("¡Datos de demostración cargados exitosamente!"))
