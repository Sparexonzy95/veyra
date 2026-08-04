from django.core.management.base import BaseCommand, CommandError

from workers.circle_wallet import (
    WorkerWalletProvisioningError,
    attach_existing_worker_wallet,
)
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = (
        "Attach an existing Circle ARC-TESTNET SCA wallet to a worker without "
        "creating another Circle wallet."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            default="veyra-code-agent",
            help="Worker slug. Defaults to veyra-code-agent.",
        )
        parser.add_argument("--wallet-set-id", required=True)
        parser.add_argument("--wallet-id", required=True)
        parser.add_argument("--address", required=True)

    def handle(self, *args, **options):
        slug = options["slug"]

        try:
            worker = WorkerAgent.objects.get(slug=slug)
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{slug}' does not exist. Run bootstrap_worker first."
            ) from exc

        try:
            result = attach_existing_worker_wallet(
                worker,
                wallet_set_id=options["wallet_set_id"],
                wallet_id=options["wallet_id"],
                address=options["address"],
            )
        except WorkerWalletProvisioningError as exc:
            raise CommandError(str(exc)) from exc

        worker.refresh_from_db()

        self.stdout.write(self.style.SUCCESS("Attached existing Circle worker wallet."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"Blockchain: {result.blockchain}")
        self.stdout.write(f"Account type: {result.account_type}")
        self.stdout.write(f"Wallet set ID: {result.wallet_set_id}")
        self.stdout.write(f"Wallet ID: {result.wallet_id}")
        self.stdout.write(f"Wallet address: {result.address}")
        self.stdout.write("No new Circle wallet was created by this command.")
        self.stdout.write("Secrets stored in database: none")
