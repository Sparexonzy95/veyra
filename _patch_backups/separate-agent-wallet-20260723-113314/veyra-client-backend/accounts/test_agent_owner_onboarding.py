from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserCapability


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
        self.assertTrue(
            UserCapability.objects.filter(
                user=user,
                code=UserCapability.Code.AGENT_OWNER,
                revoked_at__isnull=True,
            ).exists()
        )
