from django.core.management.base import BaseCommand, CommandError

from workers.claiming import (
    WorkerClaimError,
    WorkerClaimPendingError,
    reconcile_worker_job_claim,
)
from workers.models import WorkerAgent, WorkerJobQueueItem


class Command(BaseCommand):
    help = "Reconcile a pending worker claim without creating another transaction."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--queue-item-id", default=None)
        parser.add_argument("--job-id", type=int, default=None)

    def _resolve_item(self, *, slug, queue_item_id, job_id):
        try:
            worker = WorkerAgent.objects.get(slug=slug)
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(f"Worker '{slug}' does not exist.") from exc
        query = WorkerJobQueueItem.objects.filter(worker=worker)
        if queue_item_id:
            query = query.filter(pk=queue_item_id)
        elif job_id is not None:
            query = query.filter(job__onchain_job_id=job_id)
        else:
            query = query.filter(status=WorkerJobQueueItem.Status.CLAIM_PENDING)
        item = query.order_by("claim_started_at").first()
        if not item:
            raise CommandError("No matching pending claim was found.")
        return item

    def handle(self, *args, **options):
        item = self._resolve_item(
            slug=options["slug"],
            queue_item_id=options["queue_item_id"],
            job_id=options["job_id"],
        )
        try:
            result = reconcile_worker_job_claim(str(item.id))
        except WorkerClaimPendingError as exc:
            self.stdout.write(self.style.WARNING(f"Claim is still pending: {exc}"))
            self.stdout.write("No new Circle transaction was submitted.")
            self.stdout.write("Secrets displayed: none")
            return
        except WorkerClaimError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Worker job claim reconciliation completed."))
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Queue status: {result.status}")
        self.stdout.write(f"Circle state: {result.circle_state}")
        self.stdout.write(f"Arc transaction: {result.arc_transaction_hash}")
        self.stdout.write("No new Circle transaction was submitted.")
        self.stdout.write("Secrets displayed: none")
