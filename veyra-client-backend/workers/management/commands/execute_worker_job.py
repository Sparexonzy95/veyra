from django.core.management.base import BaseCommand, CommandError
from workers.execution import WorkerExecutionError, execute_worker_job
from workers.models import WorkerAgent, WorkerJobQueueItem

class Command(BaseCommand):
    help = "Execute one claimed job, validate it, push a worker branch, and open a pull request."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")
        parser.add_argument("--queue-item-id", default=None)
        parser.add_argument("--job-id", type=int, default=None)
        parser.add_argument("--confirm-live-execution", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm_live_execution"]:
            raise CommandError(
                "This command clones code, runs OpenCode, pushes a branch, and opens a pull request. "
                "Re-run with --confirm-live-execution after the read-only preflight passes."
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
            query = query.filter(status=WorkerJobQueueItem.Status.CLAIMED)
        item = query.first()
        if not item:
            raise CommandError("No matching claimed worker job was found.")
        self.stdout.write(f"Executing Arc job #{item.job.onchain_job_id}...")
        try:
            result = execute_worker_job(str(item.id))
        except WorkerExecutionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Worker coding execution completed."))
        self.stdout.write(f"Queue item: {result.queue_item_id}")
        self.stdout.write(f"Arc job: #{result.job_id}")
        self.stdout.write(f"Queue status: {result.status}")
        self.stdout.write(f"Branch: {result.branch_name}")
        self.stdout.write(f"Changed files: {len(result.changed_files)}")
        for path in result.changed_files:
            self.stdout.write(f"  - {path}")
        self.stdout.write(f"Commit: {result.commit_sha}")
        self.stdout.write(f"Pull request: {result.pull_request_url}")
        self.stdout.write(f"Baseline tests passed: {result.baseline_tests_passed}")
        self.stdout.write(f"Post-change tests passed: {result.post_tests_passed}")
        self.stdout.write("No Circle transaction was submitted.")
        self.stdout.write("GitHub, Circle, and OpenCode secrets displayed: none")
