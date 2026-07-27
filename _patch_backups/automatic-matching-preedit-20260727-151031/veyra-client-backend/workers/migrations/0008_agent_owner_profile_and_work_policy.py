# Generated for Veyra agent-owner onboarding foundation.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0007_worker_job_execution_submission"),
    ]

    operations = [
        migrations.AddField(
            model_name="workeragent",
            name="allow_database_migrations",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="allow_fork_creation",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="allow_new_dependencies",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="allowed_organizations",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="auto_claim_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="avatar_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="frameworks",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="languages",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="maximum_budget_usdc",
            field=models.DecimalField(decimal_places=6, default="5.000000", max_digits=30),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="maximum_execution_minutes",
            field=models.PositiveSmallIntegerField(default=45),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="protected_paths",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="public_repositories_only",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="specialisation",
            field=models.CharField(
                choices=[
                    ("PYTHON_BACKEND", "Python backend agent"),
                    ("JAVASCRIPT_FRONTEND", "JavaScript frontend agent"),
                    ("FULL_STACK_WEB", "Full-stack web agent"),
                    ("SMART_CONTRACT", "Smart contract agent"),
                    ("TESTING_QA", "Testing and QA agent"),
                    ("DOCUMENTATION", "Documentation agent"),
                ],
                default="PYTHON_BACKEND",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="task_types",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="testing_tools",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
