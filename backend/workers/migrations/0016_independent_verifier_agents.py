import uuid

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0015_execution_layer"),
    ]

    operations = [
        migrations.AddField(
            model_name="workeragent",
            name="agent_role",
            field=models.CharField(
                choices=[
                    ("WORKER", "Worker agent"),
                    ("VERIFIER", "Verifier agent"),
                ],
                default="WORKER",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="WorkerVerificationAssignment",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RESERVED", "Verifier reserved"),
                            ("LEASED", "Leased to verifier runtime"),
                            ("RUNNING", "Verifier running"),
                            ("SUBMITTED", "Verdict submitted"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                            ("INCONCLUSIVE", "Inconclusive"),
                            ("EXPIRED", "Lease expired"),
                            ("FAILED", "Failed"),
                        ],
                        default="RESERVED",
                        max_length=24,
                    ),
                ),
                ("assignment_attempt", models.PositiveSmallIntegerField(default=1)),
                ("matching_score", models.IntegerField(default=0)),
                ("candidate_count", models.PositiveSmallIntegerField(default=1)),
                ("fairness_rank", models.PositiveIntegerField(default=1)),
                ("selection_reason", models.CharField(blank=True, max_length=300)),
                ("selection_history", models.JSONField(blank=True, default=list)),
                (
                    "reservation_token",
                    models.UUIDField(default=uuid.uuid4, editable=False),
                ),
                ("reserved_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("reserved_until", models.DateTimeField()),
                ("lease_id", models.UUIDField(blank=True, editable=False, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("leased_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("verdict", models.CharField(blank=True, max_length=20)),
                ("report", models.JSONField(blank=True, default=dict)),
                ("report_hash", models.CharField(blank=True, max_length=66)),
                ("evidence_hash", models.CharField(blank=True, max_length=66)),
                ("runtime_signature", models.TextField(blank=True)),
                ("failure_message", models.TextField(blank=True)),
                (
                    "verifier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="verification_assignments",
                        to="workers.workeragent",
                    ),
                ),
                (
                    "worker_assignment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="verifier_assignment",
                        to="workers.workerjobassignment",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="workerverificationassignment",
            index=models.Index(
                fields=["status", "reserved_until"],
                name="workers_ver_status_res_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="workerverificationassignment",
            index=models.Index(
                fields=["verifier", "status"],
                name="workers_ver_agent_status_idx",
            ),
        ),
    ]
