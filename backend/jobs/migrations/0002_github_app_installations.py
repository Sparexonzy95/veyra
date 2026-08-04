import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("jobs", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GitHubAppInstallation",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("installation_id", models.PositiveBigIntegerField(unique=True)),
                ("account_id", models.PositiveBigIntegerField(default=0)),
                ("account_login", models.CharField(max_length=160)),
                ("account_type", models.CharField(blank=True, max_length=32)),
                ("repository_selection", models.CharField(default="selected", max_length=32)),
                ("permissions", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("CONNECTED", "Connected"), ("CHECKING", "Checking"), ("LIMITED_ACCESS", "Limited access"), ("CREDENTIAL_GENERATION_FAILED", "Credential generation failed"), ("SUSPENDED", "Suspended"), ("RECONNECT_REQUIRED", "Reconnect required"), ("DISCONNECTED", "Disconnected")], default="CHECKING", max_length=40)),
                ("suspended_at", models.DateTimeField(blank=True, null=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="github_app_installations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["account_login"]},
        ),
        migrations.CreateModel(
            name="GitHubRepositoryAccess",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("github_repository_id", models.PositiveBigIntegerField(unique=True)),
                ("owner", models.CharField(max_length=160)),
                ("name", models.CharField(max_length=160)),
                ("full_name", models.CharField(max_length=321)),
                ("private", models.BooleanField(default=False)),
                ("default_branch", models.CharField(default="main", max_length=160)),
                ("html_url", models.URLField(blank=True)),
                ("permissions", models.JSONField(blank=True, default=dict)),
                ("active", models.BooleanField(default=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("installation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="repositories", to="jobs.githubappinstallation")),
            ],
            options={"ordering": ["full_name"]},
        ),
        migrations.AddField(
            model_name="jobdraft",
            name="github_repository_access",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="job_drafts", to="jobs.githubrepositoryaccess"),
        ),
        migrations.AddIndex(model_name="githubappinstallation", index=models.Index(fields=["client", "status"], name="jobs_github_client__b41410_idx")),
        migrations.AddIndex(model_name="githubappinstallation", index=models.Index(fields=["installation_id"], name="jobs_github_install_6c1057_idx")),
        migrations.AddIndex(model_name="githubrepositoryaccess", index=models.Index(fields=["installation", "active"], name="jobs_github_install_977b4b_idx")),
        migrations.AddIndex(model_name="githubrepositoryaccess", index=models.Index(fields=["owner", "name"], name="jobs_github_owner_5d0bea_idx")),
        migrations.AddConstraint(model_name="githubrepositoryaccess", constraint=models.UniqueConstraint(fields=("installation", "full_name"), name="uniq_github_installation_repository")),
    ]
