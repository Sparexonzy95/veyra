from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserCapability, VeyraSession
from accounts.services import grant_agent_owner, grant_client, issue_session


class WorkspaceRolePermissionTests(TestCase):
    def setUp(self):
        self.client_only = User.objects.create_user(handle="client-only")
        self.owner_only = User.objects.create_user(handle="owner-only")
        self.dual_role = User.objects.create_user(handle="dual-role")
        grant_client(self.client_only)
        grant_agent_owner(self.owner_only)
        grant_client(self.dual_role)
        grant_agent_owner(self.dual_role)

    def get_as(self, user, path):
        api = APIClient()
        api.force_authenticate(user)
        return api.get(path)

    def post_as(self, user, path, data=None):
        api = APIClient()
        api.force_authenticate(user)
        return api.post(path, data or {}, format="json")

    def test_client_only_can_use_client_api_but_not_agent_owner_api(self):
        self.assertEqual(
            self.get_as(self.client_only, "/api/v1/client/dashboard/").status_code,
            200,
        )
        self.assertEqual(
            self.get_as(self.client_only, "/api/v1/agents/").status_code,
            403,
        )
        self.assertEqual(
            self.post_as(self.client_only, "/api/v1/agents/").status_code,
            403,
        )

    def test_agent_owner_only_can_use_owner_api_but_not_client_actions(self):
        self.assertEqual(
            self.get_as(self.owner_only, "/api/v1/agents/").status_code,
            200,
        )
        for path in (
            "/api/v1/client/dashboard/",
            "/api/v1/client/job-drafts/",
            "/api/v1/client/transactions/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.get_as(self.owner_only, path).status_code, 403)
        self.assertEqual(
            self.post_as(self.owner_only, "/api/v1/client/job-drafts/").status_code,
            403,
        )

    def test_dual_role_account_can_switch_without_a_second_session(self):
        request = RequestFactory().get("/", HTTP_USER_AGENT="workspace-test")
        _, session = issue_session(self.dual_role, request)
        session_count = VeyraSession.objects.filter(user=self.dual_role).count()

        grant_client(self.dual_role)
        grant_agent_owner(self.dual_role)

        self.assertEqual(
            set(
                self.dual_role.capabilities.filter(revoked_at__isnull=True)
                .values_list("code", flat=True)
            ),
            {UserCapability.Code.CLIENT, UserCapability.Code.AGENT_OWNER},
        )
        self.assertEqual(
            VeyraSession.objects.filter(user=self.dual_role).count(),
            session_count,
        )
        self.assertTrue(
            VeyraSession.objects.filter(pk=session.pk, revoked_at__isnull=True).exists()
        )
        self.assertEqual(
            self.get_as(self.dual_role, "/api/v1/client/dashboard/").status_code,
            200,
        )
        self.assertEqual(
            self.get_as(self.dual_role, "/api/v1/agents/").status_code,
            200,
        )

    def test_revoked_capability_cannot_be_used_via_direct_api_call(self):
        capability = UserCapability.objects.get(
            user=self.dual_role,
            code=UserCapability.Code.CLIENT,
        )
        from django.utils import timezone

        capability.revoked_at = timezone.now()
        capability.save(update_fields=["revoked_at"])

        self.assertEqual(
            self.get_as(self.dual_role, "/api/v1/client/dashboard/").status_code,
            403,
        )
        self.assertEqual(
            self.get_as(self.dual_role, "/api/v1/agents/").status_code,
            200,
        )
