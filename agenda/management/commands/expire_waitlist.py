"""Management command to expire past waitlisted appointments."""

from django.core.management.base import BaseCommand

from agenda.services.waitlist import expire_waitlist


class Command(BaseCommand):
    """Mark past waitlisted appointments as EXPIRED."""

    help = "Expires pending waitlisted appointments whose start_at timestamp has passed."

    def handle(self, *args, **options) -> None:
        expired_count = expire_waitlist()
        self.stdout.write(
            self.style.SUCCESS(f"Se marcaron como expiradas {expired_count} citas en espera.")
        )
