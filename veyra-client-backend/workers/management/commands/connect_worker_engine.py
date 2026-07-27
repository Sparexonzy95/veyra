from django.core.management.base import BaseCommand, CommandError

from workers.engine import connect_worker_engine
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = "Health-check OpenCode and connect it to a Veyra worker profile."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--model", default=None)

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist. Run bootstrap_worker first."
            ) from exc

        if options["model"]:
            worker.engine_model = options["model"]
            worker.save(update_fields=["engine_model", "updated_at"])

        result = connect_worker_engine(worker)
        worker.refresh_from_db()

        if not result.connected:
            raise CommandError(result.message)

        self.stdout.write(self.style.SUCCESS(f"Connected coding engine: {worker.engine_provider}"))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"Model: {worker.engine_model}")
        self.stdout.write(f"Runtime version: {worker.engine_version}")
        self.stdout.write(f"Checked at: {worker.engine_last_checked_at.isoformat()}")
        self.stdout.write("Secrets stored in database: none")
