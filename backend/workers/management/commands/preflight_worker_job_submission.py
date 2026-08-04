from django.core.management.base import BaseCommand, CommandError
from workers.models import WorkerAgent, WorkerJobQueueItem
from workers.submission import WorkerSubmissionError, preflight_worker_job_submission

class Command(BaseCommand):
    help = "Run a read-only preflight for submitWork on one completed worker job."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--queue-item-id", default=None)
        parser.add_argument("--job-id", type=int, default=None)

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(f"Worker '{options['slug']}' does not exist.") from exc
        query = WorkerJobQueueItem.objects.filter(worker=worker)
        if options["queue_item_id"]:
            query = query.filter(pk=options["queue_item_id"])
        elif options["job_id"] is not None:
            query = query.filter(job__onchain_job_id=options["job_id"])
        else:
            query = query.filter(status=WorkerJobQueueItem.Status.SUBMISSION_PENDING)
        item = query.first()
        if not item:
            raise CommandError("No matching submission-pending worker job was found.")
        try:
            result = preflight_worker_job_submission(str(item.id))
        except WorkerSubmissionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Worker job submission preflight passed."))
        self.stdout.write(f"Queue item: {result.queue_item_id}")
        self.stdout.write(f"Worker: {result.worker_slug}")
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Repository: {result.repository}")
        self.stdout.write(f"Issue: #{result.issue_number}")
        self.stdout.write(f"Pull request: {result.pull_request_url}")
        self.stdout.write(f"Git commit SHA: {result.git_commit_sha}")
        self.stdout.write(f"Commit bytes32: {result.commit_hash}")
        self.stdout.write(f"Deliverable hash: {result.deliverable_hash}")
        self.stdout.write(f"Onchain status: {result.onchain_status}")
        self.stdout.write(f"Function: {result.function_signature}")
        self.stdout.write(f"Claim deadline: {result.claim_deadline}")
        self.stdout.write(f"Seconds remaining: {result.seconds_remaining}")
        self.stdout.write("No Circle transaction was submitted.")
        self.stdout.write("No Arc state was changed.")
        self.stdout.write("Secrets displayed: none")
