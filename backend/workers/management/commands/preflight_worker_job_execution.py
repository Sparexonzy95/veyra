from django.core.management.base import BaseCommand, CommandError
from workers.execution import WorkerExecutionError, preflight_worker_job_execution
from workers.models import WorkerAgent, WorkerJobQueueItem

class Command(BaseCommand):
    help = "Run a read-only preflight for one claimed worker job execution."

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
            query = query.filter(status=WorkerJobQueueItem.Status.CLAIMED)
        item = query.first()
        if not item:
            raise CommandError("No matching claimed worker job was found.")
        try:
            result = preflight_worker_job_execution(str(item.id))
        except WorkerExecutionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Worker job execution preflight passed."))
        self.stdout.write(f"Queue item: {result.queue_item_id}")
        self.stdout.write(f"Worker: {result.worker_slug}")
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Repository: {result.repository}")
        self.stdout.write(f"Issue: #{result.issue_number} — {result.issue_title}")
        self.stdout.write(f"Onchain status: {result.onchain_status}")
        self.stdout.write(f"GitHub freshness: {result.github_freshness_code}")
        self.stdout.write(f"Branch: {result.branch_name}")
        self.stdout.write(f"Workspace: {result.workspace_name}")
        self.stdout.write("Validation commands: " + ", ".join(result.validation_commands))
        self.stdout.write(f"Claim deadline: {result.claim_deadline}")
        self.stdout.write(f"Seconds remaining: {result.seconds_remaining}")
        self.stdout.write("No repository was cloned or modified.")
        self.stdout.write("No GitHub write operation was performed.")
        self.stdout.write("No Circle transaction was submitted.")
        self.stdout.write("Secrets displayed: none")
