"""Management command to process waitlist and assign available workers."""

import datetime

from django.core.management.base import BaseCommand, CommandError

from agenda.services.waitlist import process_waitlist, process_waitlist_all


class Command(BaseCommand):
    """Process pending waitlist appointments and promote to CONFIRMED."""

    help = "Processes the waitlist for a specific date or all active dates."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--date",
            type=str,
            help="Target date to process in YYYY-MM-DD format (processes all dates if omitted).",
        )

    def handle(self, *args, **options) -> None:
        date_str = options.get("date")

        if date_str:
            try:
                target_date = datetime.date.fromisoformat(date_str)
            except ValueError as exc:
                raise CommandError("Formato de fecha inválido. Utilice YYYY-MM-DD.") from exc

            result = process_waitlist(target_date)
            assigned_count = len(result.assigned)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Fecha {target_date}: {assigned_count} citas asignadas, "
                    f"{result.remaining} restantes en espera."
                )
            )
        else:
            results = process_waitlist_all()
            total_assigned = sum(len(r.assigned) for r in results)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Procesadas {len(results)} fechas: {total_assigned} citas asignadas en total."
                )
            )
