import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0018_signed_arc_transaction_envelopes"),
    ]

    operations = [
        migrations.CreateModel(
            name="RunnerRequestNonce",
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
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("nonce_hash", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField()),
                (
                    "runner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_nonces",
                        to="workers.runnerdevice",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="runnerrequestnonce",
            constraint=models.UniqueConstraint(
                fields=("runner", "nonce_hash"),
                name="uniq_runner_request_nonce",
            ),
        ),
        migrations.AddIndex(
            model_name="runnerrequestnonce",
            index=models.Index(
                fields=["expires_at"],
                name="runner_nonce_expiry_idx",
            ),
        ),
    ]
