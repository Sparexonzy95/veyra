from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0016_independent_verifier_agents"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExecutionLayerState",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "key",
                    models.CharField(
                        default="default",
                        max_length=32,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "instance_id",
                    models.UUIDField(blank=True, editable=False, null=True),
                ),
                ("process_id", models.PositiveIntegerField(default=0)),
                ("cycle_number", models.PositiveBigIntegerField(default=0)),
                ("running", models.BooleanField(default=False)),
                (
                    "last_cycle_started_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "last_cycle_finished_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("next_cycle_at", models.DateTimeField(blank=True, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "consecutive_failures",
                    models.PositiveSmallIntegerField(default=0),
                ),
                ("last_error_code", models.CharField(blank=True, max_length=80)),
                (
                    "last_error_message",
                    models.CharField(blank=True, max_length=300),
                ),
                ("last_result", models.JSONField(blank=True, default=dict)),
            ],
        ),
        migrations.AddField(
            model_name="workerjobqueueitem",
            name="matching_next_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workerjobqueueitem",
            name="matching_retry_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
