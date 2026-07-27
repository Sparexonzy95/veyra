from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from jobs.models import VeyraJob
from workers.models import WorkerJobAssignment, WorkerJobQueueItem


class Command(BaseCommand):
    help = "Retry a claimed job after an AI provider 402 failure."

    def add_arguments(self, parser):
        parser.add_argument("--repository", required=True)
        parser.add_argument("--issue", type=int, required=True)

    def handle(self, *args, **options):
        repository = options["repository"].strip()
        issue_number = options["issue"]

        if "/" not in repository:
            raise CommandError("Repository must use OWNER/REPOSITORY format.")

        owner, name = repository.split("/", 1)

        with transaction.atomic():
            try:
                job = (
                    VeyraJob.objects
                    .select_for_update(of=("self",))
                    .select_related("draft")
                    .get(
                        draft__repository_owner__iexact=owner,
                        draft__repository_name__iexact=name,
                        draft__issue_number=issue_number,
                    )
                )
            except VeyraJob.DoesNotExist as exc:
                raise CommandError(
                    f"No job found for {repository} issue #{issue_number}."
                ) from exc

            try:
                assignment = (
                    WorkerJobAssignment.objects
                    .select_for_update(of=("self",))
                    .select_related("queue_item", "worker")
                    .get(job=job)
                )
            except WorkerJobAssignment.DoesNotExist as exc:
                raise CommandError("The job has no worker assignment.") from exc

            item = (
                WorkerJobQueueItem.objects
                .select_for_update(of=("self",))
                .get(pk=assignment.queue_item_id)
            )

            if (
                int(job.claim_deadline or 0)
                and int(timezone.now().timestamp()) >= int(job.claim_deadline)
            ):
                raise CommandError(
                    "The Arc claim deadline has expired. Recovery was refused; "
                    "use the contract refund path and create a fresh funded job."
                )

            if not item.claim_arc_transaction_hash or not item.claim_confirmed_at:
                raise CommandError(
                    "The Arc claim is not confirmed. Recovery was refused."
                )

            if (
                item.submission_circle_transaction_id
                or item.submission_arc_transaction_hash
            ):
                raise CommandError(
                    "A submission transaction already exists. Recovery was refused."
                )

            if (
                item.execution_commit_sha
                or item.execution_pull_request_number
                or item.execution_pull_request_url
            ):
                raise CommandError(
                    "GitHub execution evidence already exists. Recovery was refused."
                )

            if (
                assignment.status == WorkerJobAssignment.Status.CLAIMED
                and item.status == WorkerJobQueueItem.Status.CLAIMED
            ):
                self.stdout.write(
                    self.style.WARNING(
                        "Job is already recovered and waiting for LogicBloom."
                    )
                )
                return

            assignment.status = WorkerJobAssignment.Status.CLAIMED
            assignment.assignment_attempt = int(assignment.assignment_attempt or 0) + 1
            assignment.execution_lease_id = None
            assignment.lease_expires_at = None
            assignment.leased_at = None
            assignment.runtime_last_seen_at = None
            assignment.execution_started_at = None
            assignment.execution_completed_at = None
            assignment.evidence_hash = ""
            assignment.runtime_signature = ""
            assignment.execution_evidence = {}
            assignment.failure_stage = ""
            assignment.failure_message = ""
            assignment.save(
                update_fields=[
                    "status",
                    "assignment_attempt",
                    "execution_lease_id",
                    "lease_expires_at",
                    "leased_at",
                    "runtime_last_seen_at",
                    "execution_started_at",
                    "execution_completed_at",
                    "evidence_hash",
                    "runtime_signature",
                    "execution_evidence",
                    "failure_stage",
                    "failure_message",
                    "updated_at",
                ]
            )

            item.status = WorkerJobQueueItem.Status.CLAIMED
            item.execution_attempt_count = (
                int(item.execution_attempt_count or 0) + 1
            )
            item.execution_branch_name = ""
            item.execution_workspace_name = ""
            item.execution_baseline_test_passed = None
            item.execution_post_test_passed = False
            item.execution_changed_files = []
            item.execution_commit_sha = ""
            item.execution_pull_request_number = None
            item.execution_pull_request_url = ""
            item.execution_engine_output = ""
            item.execution_baseline_test_output = ""
            item.execution_test_output = ""
            item.execution_failure_stage = ""
            item.execution_failure_message = ""
            item.execution_started_at = None
            item.execution_completed_at = None
            item.save(
                update_fields=[
                    "status",
                    "execution_attempt_count",
                    "execution_branch_name",
                    "execution_workspace_name",
                    "execution_baseline_test_passed",
                    "execution_post_test_passed",
                    "execution_changed_files",
                    "execution_commit_sha",
                    "execution_pull_request_number",
                    "execution_pull_request_url",
                    "execution_engine_output",
                    "execution_baseline_test_output",
                    "execution_test_output",
                    "execution_failure_stage",
                    "execution_failure_message",
                    "execution_started_at",
                    "execution_completed_at",
                    "updated_at",
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Recovered {repository} issue #{issue_number}. "
                f"Arc claim preserved. Worker: {assignment.worker.name}."
            )
        )
