from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from jobs.models import VeyraJob
from workers.models import WorkerJobAssignment, WorkerJobQueueItem


class Command(BaseCommand):
    help = (
        "Safely retry one assignment that was released before any Circle or Arc "
        "claim transaction existed because of transient infrastructure failure."
    )

    def add_arguments(self, parser):
        parser.add_argument("--repository", required=True)
        parser.add_argument("--issue", type=int, required=True)

    def handle(self, *args, **options):
        repository = str(options["repository"] or "").strip()
        issue_number = int(options["issue"])
        if "/" not in repository:
            raise CommandError("Repository must be OWNER/REPOSITORY.")
        owner, name = repository.split("/", 1)

        with transaction.atomic():
            try:
                job = (
                    VeyraJob.objects.select_for_update()
                    .select_related("draft")
                    .get(
                        draft__repository_owner__iexact=owner,
                        draft__repository_name__iexact=name,
                        draft__issue_number=issue_number,
                    )
                )
            except VeyraJob.DoesNotExist as exc:
                raise CommandError(
                    f"No Veyra job exists for {repository} issue #{issue_number}."
                ) from exc

            try:
                assignment = (
                    WorkerJobAssignment.objects.select_for_update()
                    .select_related("queue_item", "worker")
                    .get(job=job)
                )
            except WorkerJobAssignment.DoesNotExist as exc:
                raise CommandError("This job has no worker assignment to recover.") from exc

            item = WorkerJobQueueItem.objects.select_for_update().get(
                pk=assignment.queue_item_id
            )

            if assignment.status != WorkerJobAssignment.Status.RELEASED:
                raise CommandError(
                    f"Assignment status is {assignment.status}, not RELEASED."
                )
            if job.status != "FUNDED" or job.client_status != "OPEN":
                raise CommandError(
                    f"Job is {job.status}/{job.client_status}; it is not safe to retry."
                )
            if item.claim_circle_transaction_id or item.claim_arc_transaction_hash:
                raise CommandError(
                    "Claim transaction metadata already exists. Reconcile it instead "
                    "of resetting the assignment."
                )

            item.status = WorkerJobQueueItem.Status.QUEUED
            item.claim_failure_stage = ""
            item.claim_failure_message = ""
            item.execution_failure_stage = ""
            item.execution_failure_message = ""
            item.save(
                update_fields=[
                    "status",
                    "claim_failure_stage",
                    "claim_failure_message",
                    "execution_failure_stage",
                    "execution_failure_message",
                    "updated_at",
                ]
            )

            now = timezone.now()
            assignment.status = WorkerJobAssignment.Status.RESERVED
            assignment.reserved_at = now
            assignment.reserved_until = now + timedelta(minutes=5)
            assignment.failure_stage = ""
            assignment.failure_message = ""
            assignment.released_at = None
            assignment.save(
                update_fields=[
                    "status",
                    "reserved_at",
                    "reserved_until",
                    "failure_stage",
                    "failure_message",
                    "released_at",
                    "updated_at",
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Recovered {repository} issue #{issue_number} for worker "
                f"{assignment.worker.name}. The execution controller may now retry it."
            )
        )
