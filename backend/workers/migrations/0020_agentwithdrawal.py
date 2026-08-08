import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0019_runnerrequestnonce"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentWithdrawal",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("destination_address", models.CharField(max_length=42, validators=[django.core.validators.RegexValidator(message="Enter a valid EVM wallet address.", regex="^0x[a-fA-F0-9]{40}$")])),
                ("amount_usdc", models.DecimalField(decimal_places=6, max_digits=30)),
                ("status", models.CharField(choices=[("SUBMITTING", "Submitting"), ("PENDING", "Pending"), ("COMPLETED", "Completed"), ("FAILED", "Failed")], default="SUBMITTING", max_length=16)),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("circle_transaction_id", models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ("arc_transaction_hash", models.CharField(blank=True, max_length=66)),
                ("failure_message", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("owner_user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="agent_withdrawals", to=settings.AUTH_USER_MODEL)),
                ("worker", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="withdrawals", to="workers.workeragent")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="agentwithdrawal", index=models.Index(fields=["worker", "status"], name="workers_age_worker__b615e7_idx")),
        migrations.AddIndex(model_name="agentwithdrawal", index=models.Index(fields=["owner_user", "created_at"], name="workers_age_owner_u_68ba70_idx")),
    ]
