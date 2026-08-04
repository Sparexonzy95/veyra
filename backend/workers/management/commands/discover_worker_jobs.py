from django.core.management.base import BaseCommand, CommandError

from workers.discovery import WorkerDiscoveryError, reconcile_worker_jobs
from workers.models import WorkerAgent


class Command(BaseCommand):
    help = (
        "Reconcile locally projected OPEN jobs against Arc and queue eligible jobs. "
        "This command never claims a job."
    )

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="veyra-code-agent")

    def handle(self, *args, **options):
        try:
            worker = WorkerAgent.objects.get(slug=options["slug"])
        except WorkerAgent.DoesNotExist as exc:
            raise CommandError(f"Worker '{options['slug']}' does not exist.") from exc

        try:
            result = reconcile_worker_jobs(worker)
        except WorkerDiscoveryError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Worker job discovery completed."))
        self.stdout.write(f"Worker: {result.worker_slug}")
        self.stdout.write(f"Discovery enabled: {str(result.discovery_enabled).lower()}")
        self.stdout.write(f"Open jobs scanned: {result.scanned}")
        self.stdout.write(f"Queued: {result.queued}")
        self.stdout.write(f"Deferred: {result.deferred}")
        self.stdout.write(f"Ineligible: {result.ineligible}")
        self.stdout.write(f"Stale: {result.stale}")
        self.stdout.write(f"Blocked: {result.blocked}")
        self.stdout.write(f"Duplicate: {result.duplicate}")
        for item in result.results:
            self.stdout.write(
                f"  Job #{item.job_id}: {item.status} "
                f"[{item.eligibility_code}] score={item.priority_score}"
            )
            self.stdout.write(f"    {item.eligibility_detail}")
            if item.required_skills:
                self.stdout.write(
                    "    Required stack: " + ", ".join(item.required_skills)
                )
                self.stdout.write(
                    "    Matched skills: "
                    + (", ".join(item.matched_skills) or "none")
                )
        self.stdout.write("No job was claimed.")
        self.stdout.write("No Circle transaction was submitted.")
        self.stdout.write("No repository was cloned or modified.")
