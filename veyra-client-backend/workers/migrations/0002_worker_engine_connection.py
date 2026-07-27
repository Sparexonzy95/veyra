from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workers", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="workeragent",
            name="engine_connection_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="engine_last_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="engine_last_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="engine_version",
            field=models.CharField(blank=True, max_length=160),
        ),
    ]