from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent
from workers.test_assignment import (
    WorkerTestAssignmentError,
    preflight_controlled_test_runtime,
)


class Command(BaseCommand):
    help = "Verify Git, OpenCode run mode, GitHub access, and workspace safety."

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
            result = preflight_controlled_test_runtime(worker)
        except WorkerTestAssignmentError as exc:
            raise CommandError(f"[{exc.stage}] {exc}") from exc

        scopes = ", ".join(result.github_scopes) or "not reported by GitHub"
        self.stdout.write(self.style.SUCCESS("Controlled test runtime preflight passed."))
        self.stdout.write(f"Git: {result.git_version}")
        self.stdout.write(f"OpenCode run mode: {result.opencode_help}")
        self.stdout.write(f"GitHub account: {result.github_username}")
        self.stdout.write(f"GitHub scopes: {scopes}")
        self.stdout.write(f"Workspace root: {result.workspace_root}")
        self.stdout.write("No repository was cloned.")
        self.stdout.write("No GitHub write operation was performed.")
        self.stdout.write("No blockchain transaction was submitted.")
