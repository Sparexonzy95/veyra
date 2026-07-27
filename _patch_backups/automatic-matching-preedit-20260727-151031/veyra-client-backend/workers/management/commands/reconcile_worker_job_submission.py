from django.core.management.base import BaseCommand, CommandError
from workers.models import WorkerAgent, WorkerJobQueueItem
from workers.submission import (
    WorkerSubmissionError,
    WorkerSubmissionPendingError,
    reconcile_worker_job_submission,
)

class Command(BaseCommand):
    help = "Reconcile a pending submitWork transaction without creating a new transaction."

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
            raise CommandError("No matching worker job was found.")
        try:
            result = reconcile_worker_job_submission(str(item.id))
        except WorkerSubmissionPendingError as exc:
            raise CommandError(str(exc)) from exc
        except WorkerSubmissionError as exc:
            raise CommandError(str(exc)) from exc
        if result is None:
            self.stdout.write("Submission remains pending; no new transaction was created.")
            return
        self.stdout.write(self.style.SUCCESS("Worker job submission reconciled."))
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Queue status: {result.status}")
        self.stdout.write(f"Circle transaction: {result.circle_transaction_id}")
        self.stdout.write(f"Circle state: {result.circle_state}")
        self.stdout.write(f"Arc transaction: {result.arc_transaction_hash}")
        self.stdout.write(f"Deliverable hash: {result.deliverable_hash}")
        self.stdout.write("No new Circle transaction was submitted.")
