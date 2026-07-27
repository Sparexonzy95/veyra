# Generated for Veyra owner-hosted connection-link onboarding.

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "workers",
            "0012_rename_workers_run_runner__584890_idx_workers_run_runner__855191_idx_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="workeragent",
            name="contract_authorisation_circle_transaction_id",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="contract_authorisation_idempotency_key",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="contract_authorisation_tx_hash",
            field=models.CharField(blank=True, max_length=66),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="provisioning_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="provisioning_stage",
            field=models.CharField(default="PROFILE", max_length=48),
        ),
        migrations.AlterField(
            model_name="workeragent",
            name="status",
            field=models.CharField(
                choices=[
                    ("SETUP_REQUIRED", "Setup required"),
                    ("PROFILE_READY", "Profile ready"),
                    ("PROVISIONING", "Provisioning"),
                    ("RUNTIME_CONNECTED", "Runtime connected"),
                    ("READY_FOR_QUALIFICATION", "Ready for qualification"),
                    ("RUNTIME_VERIFICATION_FAILED", "Runtime verification failed"),
                    ("WALLET_CREATION_FAILED", "Wallet creation failed"),
                    ("CONTRACT_AUTHORISATION_FAILED", "Contract authorisation failed"),
                    ("PROVIDER_UNAVAILABLE", "Provider unavailable"),
                    ("CONNECTION_FAILED", "Connection failed"),
                    ("ENGINE_CONNECTED", "Engine connected"),
                    ("WALLET_READY", "Wallet ready"),
                    ("PAYOUT_READY", "Payout wallet ready"),
                    ("GITHUB_READY", "GitHub ready"),
                    ("AUTHORISATION_PENDING", "Authorisation pending"),
                    ("TESTING", "Test assignment running"),
                    ("ACTIVE", "Active"),
                    ("PAUSED", "Paused"),
                    ("SUSPENDED", "Suspended"),
                ],
                default="SETUP_REQUIRED",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="HostedAgentConnection",
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
                ("runtime_id", models.CharField(max_length=160, unique=True)),
                ("runtime_url", models.URLField(max_length=500)),
                ("public_key", models.TextField()),
                (
                    "public_key_fingerprint",
                    models.CharField(max_length=64, unique=True),
                ),
                ("protocol_version", models.PositiveSmallIntegerField(default=1)),
                ("runtime_version", models.CharField(max_length=64)),
                ("provider", models.CharField(max_length=80)),
                ("model_name", models.CharField(max_length=160)),
                ("provider_ready", models.BooleanField(default=False)),
                ("capabilities", models.JSONField(blank=True, default=dict)),
                ("credential_hash", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("CONNECTING", "Connecting"),
                            ("CONNECTED", "Connected"),
                            ("UNHEALTHY", "Unhealthy"),
                            ("DISCONNECTED", "Disconnected"),
                            ("REVOKED", "Revoked"),
                        ],
                        default="CONNECTING",
                        max_length=20,
                    ),
                ),
                ("connected_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=240)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "worker",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hosted_connection",
                        to="workers.workeragent",
                    ),
                ),
            ],
            options={"ordering": ["-connected_at", "-created_at"]},
        ),
        migrations.AddIndex(
            model_name="hostedagentconnection",
            index=models.Index(
                fields=["status", "last_seen_at"],
                name="workers_hos_status_3a5d7e_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="hostedagentconnection",
            index=models.Index(
                fields=["worker", "status"],
                name="workers_hos_worker_6cb5e0_idx",
            ),
        ),
    ]
