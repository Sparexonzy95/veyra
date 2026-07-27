from django.core.management.base import BaseCommand, CommandError

from workers.circle_wallet import (
    WorkerWalletProvisioningError,
    provision_worker_wallet,
)
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = "Create or restore the Circle developer-controlled wallet for a worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            default="veyra-code-agent",
            help="Worker slug. Defaults to veyra-code-agent.",
        )

    def handle(self, *args, **options):
        slug = options["slug"]
        try:
            worker = WorkerAgent.objects.get(slug=slug)
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{slug}' does not exist. Run bootstrap_worker first."
            ) from exc

        try:
            result = provision_worker_wallet(worker)
        except WorkerWalletProvisioningError as exc:
            raise CommandError(str(exc)) from exc

        worker.refresh_from_db()
        action = "Created" if result.created else "Using existing"

        self.stdout.write(self.style.SUCCESS(f"{action} Circle worker wallet."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"Blockchain: {result.blockchain}")
        self.stdout.write(f"Account type: {result.account_type}")
        self.stdout.write(f"Wallet set ID: {result.wallet_set_id}")
        self.stdout.write(f"Wallet ID: {result.wallet_id}")
        self.stdout.write(f"Wallet address: {result.address}")
        self.stdout.write("Secrets stored in database: none")
