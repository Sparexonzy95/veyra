from django.core.management.base import BaseCommand, CommandError

from jobs.models import VeyraJob
from workers.discovery import evaluate_job
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = "Run the read-only Arc and GitHub freshness guard for one job."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--job-id", type=int, required=True)

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(f"Worker '{options['slug']}' does not exist.") from exc

        try:
            job = VeyraJob.objects.select_related("draft", "draft__funding_snapshot").get(
                onchain_job_id=options["job_id"]
            )
        except VeyraJob.DoesNotExist as exc:
            raise CommandError(f"Arc job #{options['job_id']} is not projected locally.") from exc

        result = evaluate_job(worker, job)
        github = result.github_snapshot if isinstance(result.github_snapshot, dict) else {}

        self.stdout.write("Worker job freshness check completed.")
        self.stdout.write(f"Worker: {worker.slug}")
        self.stdout.write(f"Arc job: #{job.onchain_job_id}")
        self.stdout.write(
            f"Repository: {job.draft.repository_owner}/{job.draft.repository_name}"
        )
        self.stdout.write(f"Issue: #{job.draft.issue_number} — {job.draft.issue_title}")
        self.stdout.write(f"Eligible: {str(result.passed).lower()}")
        self.stdout.write(f"Result: {result.code}")
        self.stdout.write(f"Detail: {result.detail}")
        self.stdout.write(
            f"GitHub freshness: {result.github_freshness_code or 'not reached'}"
        )
        self.stdout.write(f"GitHub issue state: {github.get('issue_state') or '-'}")
        self.stdout.write(
            f"Existing worker PR: {github.get('existing_pull_request_url') or '-'}"
        )
        self.stdout.write(
            f"Existing worker branch: {github.get('existing_branch') or '-'}"
        )
        self.stdout.write("No job was claimed.")
        self.stdout.write("No Circle transaction was submitted.")
        self.stdout.write("No GitHub write operation was performed.")
