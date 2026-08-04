import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0013_hosted_agent_connection"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerQualificationRun",
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
                ("attempt_number", models.PositiveSmallIntegerField(default=1)),
                ("task_version", models.CharField(default="python-health-v1", max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("QUEUED", "Queued"),
                            ("LEASED", "Leased to runtime"),
                            ("SUBMITTED", "Submitted"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                        ],
                        default="QUEUED",
                        max_length=16,
                    ),
                ),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("provider", models.CharField(blank=True, max_length=80)),
                ("model_name", models.CharField(blank=True, max_length=160)),
                ("runtime_version", models.CharField(blank=True, max_length=64)),
                ("submitted_files", models.JSONField(blank=True, default=list)),
                ("test_return_code", models.IntegerField(blank=True, null=True)),
                ("test_output", models.TextField(blank=True)),
                ("result_signature", models.TextField(blank=True)),
                ("failure_message", models.TextField(blank=True)),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="automatic_qualification_runs",
                        to="workers.workeragent",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="workerqualificationrun",
            constraint=models.UniqueConstraint(
                fields=("worker", "attempt_number"),
                name="uniq_worker_qualification_attempt",
            ),
        ),
        migrations.AddIndex(
            model_name="workerqualificationrun",
            index=models.Index(
                fields=["worker", "status"],
                name="wrk_qual_worker_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="workerqualificationrun",
            index=models.Index(
                fields=["status", "lease_expires_at"],
                name="wrk_qual_status_lease_idx",
            ),
        ),
    ]
