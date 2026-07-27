import uuid

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def enable_active_agent_execution(apps, schema_editor):
    WorkerAgent = apps.get_model("workers", "WorkerAgent")
    WorkerAgent.objects.filter(status="ACTIVE").update(
        auto_claim_enabled=True,
        discovery_enabled=True,
    )


def disable_active_agent_execution(apps, schema_editor):
    # Do not guess the owner's previous settings during rollback.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0014_workerqualificationrun"),
        ("jobs", "0002_github_app_installations"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workeragent",
            name="auto_claim_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="workerjobqueueitem",
            name="status",
            field=models.CharField(
                choices=[
                    ("DISCOVERED", "Discovered"),
                    ("QUEUED", "Queued for claim"),
                    ("DEFERRED", "Deferred"),
                    ("INELIGIBLE", "Ineligible"),
                    ("STALE", "No longer open"),
                    ("BLOCKED", "Blocked by task freshness guard"),
                    ("DUPLICATE", "Duplicate repository issue"),
                    ("CLAIM_PENDING", "Claim pending"),
                    ("CLAIMED", "Claimed"),
                    ("LEASED", "Leased to hosted runtime"),
                    ("EXECUTING", "Executing"),
                    ("RESULT_RECEIVED", "Runtime result received"),
                    ("SUBMISSION_PENDING", "Submission pending"),
                    ("SUBMITTED", "Submitted"),
                    ("VERIFYING", "Independent verification"),
                    ("SETTLING", "Settlement pending"),
                    ("COMPLETED", "Completed"),
                    ("FAILED", "Failed"),
                ],
                default="DISCOVERED",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="WorkerJobAssignment",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[
                    ("RESERVED", "Reserved"),
                    ("CLAIMING", "Claiming on Arc"),
                    ("CLAIMED", "Claimed"),
                    ("LEASED", "Leased to runtime"),
                    ("EXECUTING", "Executing"),
                    ("RESULT_RECEIVED", "Result received"),
                    ("SUBMITTING", "Submitting on Arc"),
                    ("SUBMITTED", "Submitted"),
                    ("VERIFYING", "Verifying"),
                    ("SETTLING", "Settling"),
                    ("COMPLETED", "Completed"),
                    ("RELEASED", "Released for reassignment"),
                    ("FAILED", "Failed"),
                ], default="RESERVED", max_length=32)),
                ("assignment_attempt", models.PositiveSmallIntegerField(default=1)),
                ("candidate_count", models.PositiveSmallIntegerField(default=1)),
                ("matching_score", models.IntegerField(default=0)),
                ("fairness_rank", models.PositiveIntegerField(default=0)),
                ("selection_reason", models.CharField(blank=True, max_length=300)),
                ("selection_history", models.JSONField(blank=True, default=list)),
                ("reservation_token", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("reserved_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("reserved_until", models.DateTimeField()),
                ("execution_lease_id", models.UUIDField(blank=True, editable=False, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("leased_at", models.DateTimeField(blank=True, null=True)),
                ("runtime_last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("execution_started_at", models.DateTimeField(blank=True, null=True)),
                ("execution_completed_at", models.DateTimeField(blank=True, null=True)),
                ("evidence_hash", models.CharField(blank=True, max_length=66)),
                ("runtime_signature", models.TextField(blank=True)),
                ("execution_evidence", models.JSONField(blank=True, default=dict)),
                ("verification_status", models.CharField(blank=True, max_length=24)),
                ("verification_report", models.JSONField(blank=True, default=dict)),
                ("verification_report_hash", models.CharField(blank=True, max_length=66)),
                ("verification_evidence_hash", models.CharField(blank=True, max_length=66)),
                ("verification_reason_hash", models.CharField(blank=True, max_length=66)),
                ("verification_started_at", models.DateTimeField(blank=True, null=True)),
                ("verification_completed_at", models.DateTimeField(blank=True, null=True)),
                ("settlement_transaction_hash", models.CharField(blank=True, max_length=66, null=True, unique=True)),
                ("settlement_receipt_block_number", models.PositiveBigIntegerField(blank=True, null=True)),
                ("settlement_started_at", models.DateTimeField(blank=True, null=True)),
                ("settlement_confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_stage", models.CharField(blank=True, max_length=80)),
                ("failure_message", models.TextField(blank=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("job", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="worker_assignment", to="jobs.veyrajob")),
                ("queue_item", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="assignment", to="workers.workerjobqueueitem")),
                ("worker", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="job_assignments", to="workers.workeragent")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="workerjobassignment",
            index=models.Index(fields=["status", "reserved_until"], name="workers_wor_status_66c05f_idx"),
        ),
        migrations.AddIndex(
            model_name="workerjobassignment",
            index=models.Index(fields=["worker", "status"], name="workers_wor_worker__fd365e_idx"),
        ),
        migrations.CreateModel(
            name="WorkerReputationSnapshot",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("karma_score", models.PositiveBigIntegerField(default=0)),
                ("completed_jobs", models.PositiveBigIntegerField(default=0)),
                ("failed_jobs", models.PositiveBigIntegerField(default=0)),
                ("abandoned_jobs", models.PositiveBigIntegerField(default=0)),
                ("total_earned_atomic", models.DecimalField(decimal_places=0, default=0, max_digits=40)),
                ("last_job_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("synced_at", models.DateTimeField(blank=True, null=True)),
                ("worker", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="reputation_snapshot", to="workers.workeragent")),
            ],
            options={"ordering": ["-karma_score", "worker_id"]},
        ),
        migrations.RunPython(enable_active_agent_execution, disable_active_agent_execution),
    ]
