from django.core.management.base import BaseCommand, CommandError

from workers.models import WorkerAgent, WorkerTestAssignment


class Command(BaseCommand):
    help = "Show the latest controlled test assignment without exposing secrets."

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
            assignment = query.order_by("-created_at").first()

        if not assignment:
            raise CommandError("No controlled test assignment exists for this worker.")

        self.stdout.write(f"Assignment ID: {assignment.id}")
        self.stdout.write(f"Status: {assignment.status}")
        self.stdout.write(
            f"Repository: {assignment.source_owner}/{assignment.source_repository}"
        )
        self.stdout.write(f"Issue: #{assignment.issue_number} — {assignment.issue_title}")
        self.stdout.write(f"Branch: {assignment.branch_name or '-'}")
        self.stdout.write(f"Baseline tests passed: {assignment.baseline_test_passed}")
        self.stdout.write(f"Post-change tests passed: {assignment.post_test_passed}")
        self.stdout.write(f"Changed files: {len(assignment.changed_files)}")
        self.stdout.write(f"Commit: {assignment.commit_sha or '-'}")
        self.stdout.write(f"Pull request: {assignment.pull_request_url or '-'}")
        self.stdout.write(f"Failure stage: {assignment.failure_stage or '-'}")
        self.stdout.write(f"Failure: {assignment.failure_message or '-'}")
        self.stdout.write(f"Worker status: {worker.status}")
        self.stdout.write(f"Discovery enabled: {str(worker.discovery_enabled).lower()}")
