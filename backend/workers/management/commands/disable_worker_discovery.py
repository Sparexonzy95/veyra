from django.core.management.base import BaseCommand, CommandError

from workers.discovery import disable_worker_discovery
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = "Disable worker job discovery without changing existing onchain jobs."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(f"Worker '{options['slug']}' does not exist.") from exc

        worker = disable_worker_discovery(worker)
        self.stdout.write(self.style.SUCCESS("Worker discovery disabled."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Discovery enabled: {str(worker.discovery_enabled).lower()}")
        self.stdout.write("Existing onchain jobs were not changed.")
