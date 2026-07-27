from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent, WorkerTestAssignment
from workers.test_assignment import (
    WorkerTestAssignmentError,
    execute_controlled_test_assignment,
)


class Command(BaseCommand):
    help = (
        "Run the prepared controlled GitHub test: clone, invoke OpenCode, test, "
        "push to the bot fork, and open a pull request."
    )

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--assignment-id", default=None)

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(
                f"Worker '{options['slug']}' does not exist."
            ) from exc

        query = WorkerTestAssignment.objects.filter(worker=worker)
        if options["assignment_id"]:
            assignment = query.filter(id=options["assignment_id"]).first()
        else:
            assignment = query.filter(
                status=WorkerTestAssignment.Status.PREPARED
            ).order_by("-created_at").first()

        if not assignment:
            raise CommandError(
                "No prepared assignment was found. Run prepare_worker_test_assignment first."
            )

        self.stdout.write(f"Running assignment: {assignment.id}")
        self.stdout.write(
            f"Repository: {assignment.source_owner}/{assignment.source_repository}"
        )
        self.stdout.write(f"Issue: #{assignment.issue_number}")
        self.stdout.write("Stage 1/7: Clone and isolate the public repository")
        self.stdout.write("Stage 2/7: Install test dependencies and run baseline tests")
        self.stdout.write("Stage 3/7: Run OpenCode with the configured GLM model")
        self.stdout.write("Stage 4/7: Inspect changed files and run post-change tests")
        self.stdout.write("Stage 5/7: Commit the validated change")
        self.stdout.write("Stage 6/7: Push to the GitHub worker fork")
        self.stdout.write("Stage 7/7: Open the pull request and activate the worker")

        try:
            result = execute_controlled_test_assignment(assignment)
        except WorkerTestAssignmentError as exc:
            raise CommandError(f"[{exc.stage}] {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Controlled test assignment passed."))
        self.stdout.write(f"Assignment ID: {result.assignment_id}")
        self.stdout.write(f"Branch: {result.branch_name}")
        self.stdout.write(f"Changed files: {len(result.changed_files)}")
        for path in result.changed_files:
            self.stdout.write(f"  - {path}")
        self.stdout.write(f"Commit: {result.commit_sha}")
        self.stdout.write(f"Pull request: {result.pull_request_url}")
        self.stdout.write(f"Worker status: {result.worker_status}")
        self.stdout.write("Discovery enabled: false")
        self.stdout.write("GitHub token stored in database: no")
        self.stdout.write("Circle and GitHub secrets passed to the OpenCode process environment: no")
