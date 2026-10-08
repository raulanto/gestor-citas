"""Management command to revalidate future worker assignments and promote waitlist."""

from django.core.management.base import BaseCommand, CommandError

from agenda.exceptions import WorkerNotFound
from agenda.services.schedules import revalidate_all, revalidate_worker


class Command(BaseCommand):
    help = "Revalida las citas futuras de los trabajadores según sus horarios vigentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker",
            type=int,
            dest="worker_id",
            help="ID del trabajador específico a revalidar.",
        )

    def handle(self, *args, **options):
        worker_id = options.get("worker_id")

        if worker_id is not None:
            self.stdout.write(f"Revalidando citas para el trabajador {worker_id}...")
            try:
                result = revalidate_worker(worker_id)
            except WorkerNotFound as exc:
                raise CommandError(str(exc.detail)) from exc

            self._report_result(result)
        else:
            self.stdout.write("Revalidando citas para todos los trabajadores...")
            results = revalidate_all()
            total_displaced = sum(len(r.displaced) for r in results)
            total_reassigned = sum(r.reassigned for r in results)
            total_waitlisted = sum(r.waitlisted for r in results)
            total_unserviceable = sum(r.unserviceable for r in results)
            total_promoted = sum(r.promoted_from_waitlist for r in results)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Revalidación completada. Trabajadores procesados: {len(results)} | "
                    f"Desplazadas: {total_displaced} (Reasignadas: {total_reassigned}, "
                    f"A espera: {total_waitlisted}, Inatendibles: {total_unserviceable}) | "
                    f"Promovidas desde espera: {total_promoted}"
                )
            )

    def _report_result(self, result):
        self.stdout.write(
            self.style.SUCCESS(
                f"Revalidación completada. Desplazadas: {len(result.displaced)} "
                f"(Reasignadas: {result.reassigned}, A espera: {result.waitlisted}, "
                f"Inatendibles: {result.unserviceable}) | "
                f"Promovidas desde espera: {result.promoted_from_waitlist}"
            )
        )
        if result.over_quota:
            self.stdout.write(
                self.style.WARNING(f"Fechas en sobrecupo: {', '.join(result.over_quota)}")
            )
