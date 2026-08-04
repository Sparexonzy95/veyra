from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent
from workers.readiness import check_worker_readiness


class Command(BaseCommand):
    help = "Run live safety checks before the worker's first test assignment."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist."
            ) from exc

        result = check_worker_readiness(worker)

        for check in result.checks:
            marker = "PASS" if check.passed else "FAIL"
            self.stdout.write(f"[{marker}] {check.name}: {check.detail}")

        if not result.ready:
            failures = ", ".join(
                check.name for check in result.checks if not check.passed
            )
            raise CommandError(f"Worker readiness failed: {failures}")

        worker.refresh_from_db()
        self.stdout.write(self.style.SUCCESS("Worker readiness checks passed."))
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {worker.status}")
        self.stdout.write("Discovery enabled: false")
        self.stdout.write("Test assignment passed: false")
        self.stdout.write("The worker is ready for its controlled test assignment.")
