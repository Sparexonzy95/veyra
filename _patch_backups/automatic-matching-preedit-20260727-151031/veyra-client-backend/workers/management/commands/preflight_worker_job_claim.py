from django.core.management.base import BaseCommand, CommandError

from workers.claiming import WorkerClaimError, preflight_worker_job_claim
from workers.models import WorkerAgent, WorkerJobQueueItem


class Command(BaseCommand):
    help = "Run a read-only live preflight for one queued worker job claim."

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
            query = query.filter(status=WorkerJobQueueItem.Status.QUEUED).order_by(
                "-priority_score", "queued_at"
            )
        item = query.first()
        if not item:
            raise CommandError("No matching worker queue item was found.")
        return item

    def handle(self, *args, **options):
        item = self._resolve_item(
            slug=options["slug"],
            queue_item_id=options["queue_item_id"],
            job_id=options["job_id"],
        )
        try:
            result = preflight_worker_job_claim(str(item.id))
        except WorkerClaimError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Worker job claim preflight passed."))
        self.stdout.write(f"Queue item: {result.queue_item_id}")
        self.stdout.write(f"Worker: {result.worker_slug}")
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Repository: {result.repository}")
        self.stdout.write(f"Issue: #{result.issue_number} — {result.issue_title}")
        self.stdout.write(f"Onchain status: {result.onchain_status}")
        self.stdout.write(f"Eligibility: {result.eligibility_code}")
        self.stdout.write(f"GitHub freshness: {result.github_freshness_code}")
        self.stdout.write(f"Contract: {result.contract_address}")
        self.stdout.write(f"Function: {result.function_signature}")
        self.stdout.write("No Circle transaction was submitted.")
        self.stdout.write("No Arc state was changed.")
        self.stdout.write("No repository was cloned or modified.")
        self.stdout.write("Secrets displayed: none")
