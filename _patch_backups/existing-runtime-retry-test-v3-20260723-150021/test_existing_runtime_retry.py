from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from workers.agent_provisioning import provision_agent
from workers.models import HostedAgentConnection, WorkerAgent


@override_settings(VEYRA_AGENT_RUNTIME_ONLINE_WINDOW_SECONDS=35)
class ExistingRuntimeRetryTests(TestCase):
    def test_retry_reuses_fresh_authenticated_runtime_without_new_link(self):
        owner = User.objects.create_user(handle="retry-owner")
        worker = WorkerAgent.objects.create(
            slug="retry-existing-runtime",
            name="Retry Existing Runtime",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=owner,
            status=WorkerAgent.Status.RUNTIME_VERIFICATION_FAILED,
            provisioning_stage="RUNTIME_VERIFICATION_FAILED",
            provisioning_error="Paste a fresh connection link from the hosted-agent server.",
            skills=["Python"],
            languages=["Python"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="zai-org/glm-5.2",
            engine_version="test-runtime/1.1",
            engine_connected=False,
            worker_wallet_address="0x6ce2f7487c1e6f8d539f6b1b999f9096222ee155",
            circle_wallet_id="circle-wallet-existing",
        )
        HostedAgentConnection.objects.create(
            worker=worker,
            runtime_id="runtime-existing-retry",
            runtime_url="http://localhost:9100",
            public_key="public-key",
            public_key_fingerprint="a" * 64,
            protocol_version=1,
            runtime_version="test-runtime/1.1",
            provider="aiand",
            model_name="zai-org/glm-5.2",
            provider_ready=True,
            capabilities={"coding": True, "testing": True},
            credential_hash="b" * 64,
            status=HostedAgentConnection.Status.CONNECTED,
            connected_at=timezone.now(),
            last_seen_at=timezone.now(),
        )

        def mark_authorised(agent):
            agent.contract_authorised = True
            agent.save(
                update_fields=[
                    "contract_authorised",
                    "updated_at",
                ]
            )

        with (
            patch("workers.agent_provisioning.connect_hosted_agent") as connect,
            patch("workers.agent_provisioning.provision_worker_wallet"),
            patch(
                "workers.agent_provisioning.authorise_worker_contract",
                side_effect=mark_authorised,
            ),
        ):
            result = provision_agent(worker)

        connect.assert_not_called()
        worker.refresh_from_db()
        self.assertEqual(result.stage, "READY_FOR_QUALIFICATION")
        self.assertEqual(worker.status, WorkerAgent.Status.READY_FOR_QUALIFICATION)
        self.assertEqual(worker.provisioning_error, "")
        self.assertTrue(worker.contract_authorised)
