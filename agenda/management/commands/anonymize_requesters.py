"""Management command to anonymize old requester data."""

from django.conf import settings
from django.core.management.base import BaseCommand

from agenda.services.retention import anonymize_requesters


class Command(BaseCommand):
    """Anonymize PII for requesters whose appointments are all terminal and older than threshold."""

    help = "Anonimiza datos personales de solicitantes antiguos con citas finalizadas."

    def add_arguments(self, parser) -> None:
        default_days = getattr(settings, "PII_RETENTION_DAYS", 730)
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=default_days,
            help=f"Antigüedad en días para anonimizar (default: {default_days}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula la anonimización sin modificar la base de datos.",
        )

    def handle(self, *args, **options) -> None:
        older_than_days = options["older_than_days"]
        dry_run = options["dry_run"]

        count = anonymize_requesters(older_than_days=older_than_days, dry_run=dry_run)

        mode_str = " (dry-run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Solicitantes anonimizados{mode_str}: {count} "
                f"(antigüedad > {older_than_days} días)."
            )
        )
