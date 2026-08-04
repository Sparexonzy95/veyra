import os
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from workers.github_bot import GitHubBotConnectionError, connect_worker_github
from workers.models import WorkerAgent


class WorkerGitHubBotTests(TestCase):
    def setUp(self):
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            description="Test worker",
            owner_type=WorkerAgent.OwnerType.VEYRA,
            status=WorkerAgent.Status.PAYOUT_READY,
            skills=["Python"],
            engine_provider=WorkerAgent.EngineProvider.OPENCODE,
            engine_model="zai-org/glm-5.2",
            engine_connected=True,
            engine_version="1.17.18",
            engine_last_checked_at=timezone.now(),
            circle_wallet_id="fecb6750-b81f-56f7-a229-091e876c4a36",
            circle_wallet_set_id="6839ea61-5756-507c-b751-b63d8a69c819",
            worker_wallet_address="0x7e1efab63cb37b0550c9cf23d81622b66a31ea33",
            wallet_blockchain="ARC-TESTNET",
            wallet_account_type="SCA",
            payout_wallet_address="0x7e1efab63cb37b0550c9cf23d81622b66a31ea33",
        )

    def _response(self, *, login="veyra-worker-bot", status=200):
        response = Mock()
        response.status_code = status
        response.json.return_value = {
            "login": login,
            "id": 123456,
            "type": "User",
            "url": f"https://api.github.com/users/{login}",
        }
        return response

    @patch.dict(
        os.environ,
        {
            "GITHUB_BOT_TOKEN": "test-token",
            "GITHUB_BOT_USERNAME": "veyra-worker-bot",
        },
        clear=False,
    )
    @patch("workers.github_bot.httpx.Client")
    def test_connects_expected_bot_without_storing_token(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.get.return_value = self._response()

        result = connect_worker_github(self.worker)
        self.worker.refresh_from_db()

        self.assertTrue(result.connected)
        self.assertEqual(self.worker.github_username, "veyra-worker-bot")
        self.assertTrue(self.worker.github_connected)
        self.assertEqual(self.worker.status, WorkerAgent.Status.GITHUB_READY)

        field_names = {field.name for field in WorkerAgent._meta.get_fields()}
        self.assertNotIn("github_token", field_names)
        self.assertNotIn("github_bot_token", field_names)

    @patch.dict(
        os.environ,
        {
            "GITHUB_BOT_TOKEN": "test-token",
            "GITHUB_BOT_USERNAME": "veyra-worker-bot",
        },
        clear=False,
    )
    @patch("workers.github_bot.httpx.Client")
    def test_rejects_token_for_wrong_account(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.get.return_value = self._response(login="different-user")

        with self.assertRaises(GitHubBotConnectionError):
            connect_worker_github(self.worker)

        self.worker.refresh_from_db()
        self.assertFalse(self.worker.github_connected)

    @patch.dict(
        os.environ,
        {
            "GITHUB_BOT_TOKEN": "test-token",
            "GITHUB_BOT_USERNAME": "veyra-worker-bot",
        },
        clear=False,
    )
    @patch("workers.github_bot.httpx.Client")
    def test_management_command_connects_bot(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.get.return_value = self._response()

        call_command("connect_worker_github")

        self.worker.refresh_from_db()
        self.assertTrue(self.worker.github_connected)
        self.assertEqual(self.worker.status, WorkerAgent.Status.GITHUB_READY)

    @patch.dict(
        os.environ,
        {
            "GITHUB_BOT_TOKEN": "",
            "GITHUB_BOT_USERNAME": "veyra-worker-bot",
        },
        clear=False,
    )
    def test_command_rejects_missing_token(self):
        with self.assertRaises(CommandError):
            call_command("connect_worker_github")
