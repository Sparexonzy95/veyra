from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent
from workers.readiness import (
    WorkerReadinessError,
    sync_worker_contract_authorisation,
)


class Command(BaseCommand):
    help = "Read the worker's escrow authorisation from Arc and sync it to Django."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist."
            ) from exc

        try:
            result = sync_worker_contract_authorisation(worker)
        except WorkerReadinessError as exc:
            raise CommandError(str(exc)) from exc

        worker.refresh_from_db()

        if not result.authorised:
            raise CommandError(
                "The worker wallet is not authorised by the Veyra escrow contract."
            )

        self.stdout.write(self.style.SUCCESS("Worker contract authorisation synchronized."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"Chain ID: {result.chain_id}")
        self.stdout.write(f"Contract: {result.contract_address}")
        self.stdout.write(f"Worker wallet: {result.worker_address}")
        self.stdout.write(f"Agent authorised: {result.authorised}")
        self.stdout.write(f"Verifier authorised: {result.verifier_authorised}")
        self.stdout.write(f"Contract paused: {result.contract_paused}")
        self.stdout.write(f"Checked at: {result.checked_at}")
        self.stdout.write("No transaction was submitted by this command.")
