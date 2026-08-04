from django.test import TestCase
from rest_framework.test import APIClient

from wallets.models import WalletAccount

from accounts.models import AgentOwnerProfile, User, UserCapability


class AgentOwnerOnboardingTests(TestCase):
    def test_authenticated_user_can_add_agent_owner_role(self):
        user = User.objects.create_user(handle="future-agent-owner")
        client = APIClient()
        client.force_authenticate(user)

        response = client.post(
            "/api/v1/onboarding/agent-owner/",
            {"timezone": "Africa/Lagos"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["capability"], UserCapability.Code.AGENT_OWNER)
        self.assertFalse(response.data["wallet_setup_required"])
        self.assertEqual(
            response.data["agent_wallet_policy"],
            "PER_AGENT_DEVELOPER_CONTROLLED",
        )
        self.assertTrue(
            UserCapability.objects.filter(
                user=user,
                code=UserCapability.Code.AGENT_OWNER,
                revoked_at__isnull=True,
            ).exists()
        )

    def test_agent_owner_wallet_is_identity_only_until_client_workspace_is_enabled(self):
        user = User.objects.create_user(handle="agent-owner-wallet")
        wallet = WalletAccount.objects.create(
            user=user,
            circle_wallet_id="identity-wallet",
            address="0x1111111111111111111111111111111111111111",
            blockchain="ARC-TESTNET",
        )
        client = APIClient()
        client.force_authenticate(user)

        response = client.post(
            "/api/v1/onboarding/agent-owner/",
            {
                "notification_email": "owner@example.com",
                "timezone": "Africa/Lagos",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        wallet.refresh_from_db()
        self.assertEqual(wallet.purpose, WalletAccount.Purpose.IDENTITY_ONLY)
        profile = AgentOwnerProfile.objects.get(user=user)
        self.assertEqual(profile.notification_email, "owner@example.com")
        self.assertEqual(profile.timezone, "Africa/Lagos")

