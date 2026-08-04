from django.core.management.base import BaseCommand, CommandError
from workers.models import WorkerAgent, WorkerJobQueueItem
from workers.submission import (
    WorkerSubmissionError,
    WorkerSubmissionPendingError,
    execute_worker_job_submission,
)

class Command(BaseCommand):
    help = "Submit one live submitWork transaction through the worker Circle SCA wallet."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--queue-item-id", default=None)
        parser.add_argument("--job-id", type=int, default=None)
        parser.add_argument("--confirm-live-submission", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm_live_submission"]:
            raise CommandError(
                "This command submits a live Arc submitWork transaction. Re-run with "
                "--confirm-live-submission after the read-only preflight passes."
            )
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
        self.stdout.write(f"Submitting Arc work for job #{item.job.onchain_job_id}...")
        try:
            result = execute_worker_job_submission(str(item.id))
        except WorkerSubmissionPendingError as exc:
            raise CommandError(
                f"Submission outcome is pending: {exc} Do not resubmit; run "
                f"python manage.py reconcile_worker_job_submission --queue-item-id {item.id}"
            ) from exc
        except WorkerSubmissionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Worker job submission confirmed on Arc."))
        self.stdout.write(f"Queue item: {result.queue_item_id}")
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Queue status: {result.status}")
        self.stdout.write(f"Circle transaction: {result.circle_transaction_id}")
        self.stdout.write(f"Circle state: {result.circle_state}")
        self.stdout.write(f"Arc transaction: {result.arc_transaction_hash}")
        self.stdout.write(f"Receipt block: {result.receipt_block_number or '-'}")
        self.stdout.write(f"Commit hash: {result.commit_hash}")
        self.stdout.write(f"Deliverable hash: {result.deliverable_hash}")
        self.stdout.write(f"Pull request: #{result.pull_request_number}")
        self.stdout.write("GitHub, Circle, and OpenCode secrets displayed: none")
