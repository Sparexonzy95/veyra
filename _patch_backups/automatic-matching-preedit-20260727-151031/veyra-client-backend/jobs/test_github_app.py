import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from accounts.services import grant_client, issue_session
from jobs.github_app import (
    create_install_state,
    parse_install_state,
    verify_webhook_signature,
)
from jobs.models import GitHubAppInstallation, GitHubRepositoryAccess


@override_settings(
    GITHUB_APP_ID="12345",
    GITHUB_APP_SLUG="veyra-test-app",
    GITHUB_APP_PRIVATE_KEY="test-private-key",
    GITHUB_WEBHOOK_SECRET="webhook-secret",
    GITHUB_APP_INSTALL_URL="",
)
class GitHubAppApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(display_name="GitHub Client")
        grant_client(self.user)
        raw, _ = issue_session(self.user, type("Request", (), {"headers": {}})())
        self.client = APIClient()
        self.client.cookies[settings.VEYRA_SESSION_COOKIE] = raw

    def test_install_state_is_tied_to_client(self):
        state = create_install_state(user_id=str(self.user.id), return_path="/dashboard/jobs")
        payload = parse_install_state(state, user_id=str(self.user.id))
        self.assertEqual(payload["return_path"], "/dashboard/jobs")

    def test_status_starts_disconnected(self):
        response = self.client.get("/api/v1/client/github/app/status/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["configured"])
        self.assertFalse(response.data["connected"])
        self.assertEqual(response.data["connection_state"], "DISCONNECTED")

    def test_install_start_returns_github_app_url(self):
        response = self.client.post(
            "/api/v1/client/github/app/install/start/",
            {"return_path": "/dashboard/jobs"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("github.com/apps/veyra-test-app/installations/new", response.data["install_url"])
        self.assertIn("state=", response.data["install_url"])

    @patch("jobs.github_views.sync_installation")
    def test_install_complete_links_repositories(self, sync_installation):
        installation = GitHubAppInstallation.objects.create(
            client=self.user,
            installation_id=901,
            account_id=55,
            account_login="example-org",
            account_type="Organization",
            permissions={
                "contents": "write",
                "issues": "read",
                "pull_requests": "write",
                "checks": "read",
            },
            status=GitHubAppInstallation.Status.CONNECTED,
        )
        GitHubRepositoryAccess.objects.create(
            installation=installation,
            github_repository_id=902,
            owner="example-org",
            name="api",
            full_name="example-org/api",
            active=True,
        )
        sync_installation.return_value = installation
        state = create_install_state(user_id=str(self.user.id), return_path="/dashboard/jobs")
        response = self.client.post(
            "/api/v1/client/github/app/install/complete/",
            {"state": state, "installation_id": 901},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["installation"]["status"], "CONNECTED")
        self.assertEqual(response.data["repositories"][0]["full_name"], "example-org/api")


    def test_connected_installation_without_repository_is_not_job_ready(self):
        GitHubAppInstallation.objects.create(
            client=self.user,
            installation_id=903,
            account_id=56,
            account_login="empty-org",
            account_type="Organization",
            permissions={
                "contents": "write",
                "issues": "read",
                "pull_requests": "write",
                "checks": "read",
            },
            status=GitHubAppInstallation.Status.CONNECTED,
        )
        response = self.client.get("/api/v1/client/github/app/status/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["connected"])

    @patch("jobs.github_views.list_repository_issues")
    def test_client_can_list_open_issues_for_approved_repository(self, list_issues):
        installation = GitHubAppInstallation.objects.create(
            client=self.user,
            installation_id=904,
            account_id=57,
            account_login="example-org",
            account_type="Organization",
            permissions={
                "contents": "write",
                "issues": "read",
                "pull_requests": "write",
                "checks": "read",
            },
            status=GitHubAppInstallation.Status.CONNECTED,
        )
        repository = GitHubRepositoryAccess.objects.create(
            installation=installation,
            github_repository_id=905,
            owner="example-org",
            name="api",
            full_name="example-org/api",
            active=True,
        )
        list_issues.return_value = [
            {
                "number": 12,
                "title": "Add task statistics endpoint",
                "state": "open",
                "html_url": "https://github.com/example-org/api/issues/12",
                "updated_at": "2026-07-23T10:00:00Z",
                "author_login": "client",
                "labels": ["backend"],
            }
        ]

        response = self.client.get(
            f"/api/v1/client/github/app/repositories/{repository.id}/issues/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["repository"]["full_name"], "example-org/api")
        self.assertEqual(response.data["issues"][0]["number"], 12)
        self.assertNotIn("token", str(response.data).lower())

    def test_issue_preview_requires_an_approved_repository(self):
        response = self.client.post(
            "/api/v1/client/github/issue-preview/",
            {"github_issue_url": "https://github.com/example/private/issues/1"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not connected", str(response.data).lower())

    def test_webhook_signature_verification(self):
        body = json.dumps({"zen": "safe"}).encode()
        signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(body=body, signature=signature))
        self.assertFalse(verify_webhook_signature(body=body, signature="sha256=bad"))
