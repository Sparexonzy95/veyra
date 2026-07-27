import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0002_worker_engine_connection"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerTestAssignment",
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
                            ("PREPARED", "Prepared"),
                            ("RUNNING", "Running"),
                            ("ENGINE_COMPLETED", "Engine completed"),
                            ("TESTS_PASSED", "Tests passed"),
                            ("PR_OPENED", "Pull request opened"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                        ],
                        default="PREPARED",
                        max_length=24,
                    ),
                ),
                ("issue_url", models.URLField()),
                ("repository_url", models.URLField()),
                ("source_owner", models.CharField(max_length=120)),
                ("source_repository", models.CharField(max_length=120)),
                ("issue_number", models.PositiveBigIntegerField()),
                ("issue_title", models.CharField(max_length=240)),
                ("issue_body", models.TextField(blank=True)),
                (
                    "acceptance_criteria",
                    models.JSONField(blank=True, default=list),
                ),
                ("base_branch", models.CharField(default="main", max_length=120)),
                ("fork_owner", models.CharField(blank=True, max_length=120)),
                ("fork_repository", models.CharField(blank=True, max_length=120)),
                ("branch_name", models.CharField(blank=True, max_length=180)),
                ("workspace_name", models.CharField(blank=True, max_length=180)),
                (
                    "baseline_test_command",
                    models.CharField(blank=True, max_length=240),
                ),
                (
                    "post_test_command",
                    models.CharField(blank=True, max_length=240),
                ),
                ("baseline_test_passed", models.BooleanField(blank=True, null=True)),
                ("post_test_passed", models.BooleanField(default=False)),
                ("changed_files", models.JSONField(blank=True, default=list)),
                ("commit_sha", models.CharField(blank=True, max_length=64)),
                (
                    "pull_request_number",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                ("pull_request_url", models.URLField(blank=True)),
                ("engine_output", models.TextField(blank=True)),
                ("baseline_test_output", models.TextField(blank=True)),
                ("test_output", models.TextField(blank=True)),
                ("failure_stage", models.CharField(blank=True, max_length=80)),
                ("failure_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="test_assignments",
                        to="workers.workeragent",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["worker", "status"],
                        name="workers_wor_worker__838c77_idx",
                    ),
                    models.Index(
                        fields=["source_owner", "source_repository", "issue_number"],
                        name="workers_wor_source__884842_idx",
                    ),
                ],
            },
        ),
    ]
