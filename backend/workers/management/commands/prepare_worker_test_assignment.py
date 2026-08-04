from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent
from workers.test_assignment import (
    DEFAULT_TEST_ISSUE_URL,
    DEFAULT_TEST_REPOSITORY_URL,
    WorkerTestAssignmentError,
    prepare_controlled_test_assignment,
)


class Command(BaseCommand):
    help = "Prepare the controlled public GitHub test assignment for a worker."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument(
            "--repository-url",
            default=DEFAULT_TEST_REPOSITORY_URL,
        )
        parser.add_argument(
            "--issue-url",
            default=DEFAULT_TEST_ISSUE_URL,
        )

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist."
            ) from exc

        try:
            assignment = prepare_controlled_test_assignment(
                worker,
                repository_url=options["repository_url"],
                issue_url=options["issue_url"],
            )
        except WorkerTestAssignmentError as exc:
            raise CommandError(f"[{exc.stage}] {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Controlled test assignment prepared."))
        self.stdout.write(f"Assignment ID: {assignment.id}")
        self.stdout.write(f"Worker: {worker.name}")
        self.stdout.write(f"Status: {assignment.status}")
        self.stdout.write(
            f"Repository: {assignment.source_owner}/{assignment.source_repository}"
        )
        self.stdout.write(
            f"Issue: #{assignment.issue_number} — {assignment.issue_title}"
        )
        self.stdout.write(f"Base branch: {assignment.base_branch}")
        self.stdout.write(f"Worker branch: {assignment.branch_name}")
        self.stdout.write(f"Workspace name: {assignment.workspace_name}")
        self.stdout.write("Repository visibility: public")
        self.stdout.write("No repository was cloned and no code was changed yet.")
