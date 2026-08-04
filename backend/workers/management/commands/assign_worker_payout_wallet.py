from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent


class Command(BaseCommand):
    help = (
        "Assign a worker payout wallet. By default, the MVP uses the worker's "
        "operational Circle wallet as its temporary payout wallet."
    )

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument(
            "--address",
            default=None,
            help=(
                "Optional payout address. When omitted, use the worker's "
                "operational wallet address."
            ),
        )

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist."
            ) from exc

        if not worker.circle_wallet_id or not worker.worker_wallet_address:
            raise CommandError(
                "The worker operational wallet is not ready."
            )

        payout_address = (
            options["address"] or worker.worker_wallet_address
        ).strip()

        if (
            worker.payout_wallet_address
            and worker.payout_wallet_address.lower() != payout_address.lower()
        ):
            raise CommandError(
                "This worker already has a different payout wallet. "
                "Refusing to overwrite it."
            )

        worker.payout_wallet_address = payout_address

        if worker.status in {
            WorkerAgent.Status.SETUP_REQUIRED,
            WorkerAgent.Status.PROFILE_READY,
            WorkerAgent.Status.ENGINE_CONNECTED,
            WorkerAgent.Status.WALLET_READY,
            WorkerAgent.Status.PAYOUT_READY,
        }:
            worker.status = WorkerAgent.Status.PAYOUT_READY

        try:
            worker.save(
                update_fields=[
                    "payout_wallet_address",
                    "status",
                    "discovery_enabled",
                    "updated_at",
                ]
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Assigned worker payout wallet."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"Operational wallet: {worker.worker_wallet_address}")
        self.stdout.write(f"Payout wallet: {worker.payout_wallet_address}")
        self.stdout.write("MVP mode: operational wallet also receives payouts")
        self.stdout.write("Secrets stored in database: none")
