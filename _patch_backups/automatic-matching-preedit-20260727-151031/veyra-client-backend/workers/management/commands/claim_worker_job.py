from django.core.management.base import BaseCommand, CommandError

from workers.claiming import (
    WorkerClaimError,
    WorkerClaimPendingError,
    execute_worker_job_claim,
)
from workers.models import WorkerAgent, WorkerJobQueueItem


class Command(BaseCommand):
    help = "Submit one live claimJob(uint256) transaction through the worker Circle SCA wallet."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--queue-item-id", default=None)
        parser.add_argument("--job-id", type=int, default=None)
        parser.add_argument("--confirm-live-claim", action="store_true")

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
            query = query.filter(status=WorkerJobQueueItem.Status.QUEUED).order_by(
                "-priority_score", "queued_at"
            )
        item = query.first()
        if not item:
            raise CommandError("No matching worker queue item was found.")
        return item

    def handle(self, *args, **options):
        if not options["confirm_live_claim"]:
            raise CommandError(
                "This command submits a live Arc claim transaction. Re-run with "
                "--confirm-live-claim after the read-only preflight passes."
            )
        item = self._resolve_item(
            slug=options["slug"],
            queue_item_id=options["queue_item_id"],
            job_id=options["job_id"],
        )
        self.stdout.write(f"Submitting live claim for Arc job #{item.job.onchain_job_id}...")
        try:
            result = execute_worker_job_claim(str(item.id))
        except WorkerClaimPendingError as exc:
            raise CommandError(
                f"Claim outcome is pending: {exc} Do not submit another claim; run "
                f"python manage.py reconcile_worker_job_claim --queue-item-id {item.id}"
            ) from exc
        except WorkerClaimError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Worker job claim confirmed on Arc."))
        self.stdout.write(f"Queue item: {result.queue_item_id}")
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Queue status: {result.status}")
        self.stdout.write(f"Circle transaction: {result.circle_transaction_id}")
        self.stdout.write(f"Circle state: {result.circle_state}")
        self.stdout.write(f"Arc transaction: {result.arc_transaction_hash}")
        self.stdout.write(f"Receipt block: {result.receipt_block_number or '-'}")
        self.stdout.write(f"Provider: {result.provider_address}")
        self.stdout.write(f"Claim deadline: {result.claim_deadline}")
        self.stdout.write("GitHub, Circle, and OpenCode secrets displayed: none")
