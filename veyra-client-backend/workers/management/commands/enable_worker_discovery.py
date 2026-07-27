from django.core.management.base import BaseCommand, CommandError

from workers.discovery import WorkerDiscoveryError, enable_worker_discovery
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = "Enable read-only autonomous job discovery for an ACTIVE worker."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(f"Worker '{options['slug']}' does not exist.") from exc

        try:
            worker = enable_worker_discovery(worker)
        except WorkerDiscoveryError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Worker discovery enabled."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write(f"Discovery enabled: {str(worker.discovery_enabled).lower()}")
        self.stdout.write("Mode: read-only discovery and queueing")
        self.stdout.write("No job was claimed.")
        self.stdout.write("No Circle transaction was submitted.")
        self.stdout.write("No repository was cloned or modified.")
