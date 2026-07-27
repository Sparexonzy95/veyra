import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from workers.models import WorkerAgent, WorkerTestAssignment
from workers.test_assignment import (
    CommandResult,
    GitHubRepositoryIssue,
    WorkerTestAssignmentError,
    _activate_worker_after_test,
    _engine_args,
    _extract_acceptance_criteria,
    _git_auth_environment,
    _run_command,
    _validate_changed_files,
    verify_noninteractive_git_credentials,
    execute_controlled_test_assignment,
    prepare_controlled_test_assignment,
)


class WorkerTestAssignmentServiceTests(TestCase):
    def setUp(self):
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            description="Controlled test worker",
            owner_type=WorkerAgent.OwnerType.VEYRA,
            status=WorkerAgent.Status.TESTING,
            skills=["Python", "Flask", "Pytest"],
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
            github_username="logicbloomlab",
            github_connected=True,
            contract_authorised=True,
        )
        self.issue = GitHubRepositoryIssue(
            owner="sparexonzy95",
            repository="veyra-agent-test-api",
            repository_url="https://github.com/sparexonzy95/veyra-agent-test-api",
            visibility="public",
            default_branch="main",
            issue_number=1,
            issue_url=(
                "https://github.com/sparexonzy95/veyra-agent-test-api/issues/1"
            ),
            issue_title="Add the health endpoint",
            issue_body="## Acceptance Criteria\n- Return status ok\n- Add tests",
            issue_state="open",
            acceptance_criteria=("Return status ok", "Add tests"),
        )

    @patch("workers.test_assignment.check_github_bot")
    def test_prepare_creates_sanitized_assignment(self, check_bot):
        client = Mock()
        client.load_repository_issue.return_value = self.issue

        assignment = prepare_controlled_test_assignment(
            self.worker,
            github_client=client,
        )

        self.assertEqual(assignment.status, WorkerTestAssignment.Status.PREPARED)
        self.assertEqual(assignment.issue_number, 1)
        self.assertEqual(assignment.acceptance_criteria, ["Return status ok", "Add tests"])
        self.assertTrue(assignment.branch_name.startswith("veyra/test-issue-1-"))
        self.assertIn("veyra-agent-test-api-issue-1", assignment.workspace_name)
        check_bot.assert_called_once_with(expected_username="logicbloomlab")

    @patch("workers.test_assignment.check_github_bot")
    def test_prepare_reuses_active_assignment(self, check_bot):
        client = Mock()
        client.load_repository_issue.return_value = self.issue

        first = prepare_controlled_test_assignment(self.worker, github_client=client)
        second = prepare_controlled_test_assignment(self.worker, github_client=client)

        self.assertEqual(first.id, second.id)
        self.assertEqual(WorkerTestAssignment.objects.count(), 1)

    def test_prepare_rejects_worker_that_is_not_testing(self):
        self.worker.status = WorkerAgent.Status.GITHUB_READY
        self.worker.save(update_fields=["status", "discovery_enabled", "updated_at"])

        with self.assertRaises(WorkerTestAssignmentError) as context:
            prepare_controlled_test_assignment(self.worker, github_client=Mock())

        self.assertEqual(context.exception.stage, "worker_state")

    def test_assignment_cannot_pass_without_pr_and_tests(self):
        assignment = WorkerTestAssignment(
            worker=self.worker,
            status=WorkerTestAssignment.Status.PASSED,
            issue_url=self.issue.issue_url,
            repository_url=self.issue.repository_url,
            source_owner=self.issue.owner,
            source_repository=self.issue.repository,
            issue_number=1,
            issue_title=self.issue.issue_title,
        )

        with self.assertRaises(ValidationError):
            assignment.full_clean()

    def test_activation_requires_passing_assignment(self):
        assignment = WorkerTestAssignment.objects.create(
            worker=self.worker,
            status=WorkerTestAssignment.Status.PREPARED,
            issue_url=self.issue.issue_url,
            repository_url=self.issue.repository_url,
            source_owner=self.issue.owner,
            source_repository=self.issue.repository,
            issue_number=1,
            issue_title=self.issue.issue_title,
        )

        with self.assertRaises(WorkerTestAssignmentError):
            _activate_worker_after_test(self.worker, assignment)

    def test_activation_sets_worker_active_but_leaves_discovery_disabled(self):
        assignment = WorkerTestAssignment.objects.create(
            worker=self.worker,
            status=WorkerTestAssignment.Status.PASSED,
            issue_url=self.issue.issue_url,
            repository_url=self.issue.repository_url,
            source_owner=self.issue.owner,
            source_repository=self.issue.repository,
            issue_number=1,
            issue_title=self.issue.issue_title,
            post_test_passed=True,
            commit_sha="a" * 40,
            pull_request_number=2,
            pull_request_url=(
                "https://github.com/sparexonzy95/veyra-agent-test-api/pull/2"
            ),
        )

        _activate_worker_after_test(self.worker, assignment)
        self.worker.refresh_from_db()

        self.assertEqual(self.worker.status, WorkerAgent.Status.ACTIVE)
        self.assertTrue(self.worker.test_assignment_passed)
        self.assertFalse(self.worker.discovery_enabled)
        self.assertIsNotNone(self.worker.activated_at)


    def test_execute_full_controlled_flow_activates_worker(self):
        assignment = WorkerTestAssignment.objects.create(
            worker=self.worker,
            status=WorkerTestAssignment.Status.PREPARED,
            issue_url=self.issue.issue_url,
            repository_url=self.issue.repository_url,
            source_owner=self.issue.owner,
            source_repository=self.issue.repository,
            issue_number=1,
            issue_title=self.issue.issue_title,
            issue_body=self.issue.issue_body,
            acceptance_criteria=list(self.issue.acceptance_criteria),
            base_branch="main",
            fork_owner="logicbloomlab",
            fork_repository=self.issue.repository,
            branch_name="veyra/test-issue-1-integration",
            workspace_name="integration-workspace",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=source,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "source@example.com"],
                cwd=source,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Source"],
                cwd=source,
                check=True,
            )
            (source / "requirements.txt").write_text(
                "pytest==8.3.5\n", encoding="utf-8"
            )
            (source / "app.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=source, check=True)
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=source,
                check=True,
                capture_output=True,
            )

            from workers import test_assignment as service

            original_runner = service._run_command

            def command_runner(command, *, cwd, timeout, env=None):
                command = list(command)
                if len(command) > 1 and command[1] == "clone":
                    command[-2] = str(source)
                if len(command) > 1 and command[1] == "push":
                    self.assertIsNotNone(env)
                    self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
                    self.assertEqual(env.get("GCM_INTERACTIVE"), "Never")
                    self.assertEqual(env.get("GCM_GUI_PROMPT"), "0")
                    self.assertEqual(env.get("GIT_CONFIG_KEY_0"), "credential.helper")
                    self.assertEqual(env.get("GIT_CONFIG_VALUE_0"), "")
                    self.assertEqual(env.get("VEYRA_GIT_USERNAME"), "logicbloomlab")
                    self.assertEqual(env.get("VEYRA_GIT_TOKEN"), "test-token")
                    return CommandResult(0, "pushed", "")
                return original_runner(command, cwd=Path(cwd), timeout=timeout, env=env)

            def engine_runner(_assignment, workspace):
                (workspace / "app.py").write_text("value = 2\n", encoding="utf-8")
                return CommandResult(0, "engine complete", "")

            github = Mock()
            github.token = "test-token"
            github.authenticated_user.return_value = {
                "login": "logicbloomlab",
                "id": 227142916,
            }
            github.ensure_fork.return_value = {
                "clone_url": (
                    "https://github.com/logicbloomlab/"
                    "veyra-agent-test-api.git"
                )
            }
            github.open_pull_request.return_value = {
                "number": 7,
                "html_url": (
                    "https://github.com/sparexonzy95/"
                    "veyra-agent-test-api/pull/7"
                ),
            }

            with patch(
                "workers.test_assignment._workspace_root",
                return_value=root,
            ), patch(
                "workers.test_assignment._prepare_python_test_environment",
                return_value=(Path(sys.executable), "python -m pytest -q"),
            ), patch(
                "workers.test_assignment._run_pytest",
                return_value=CommandResult(0, "1 passed", ""),
            ):
                result = execute_controlled_test_assignment(
                    assignment,
                    github_client=github,
                    command_runner=command_runner,
                    engine_runner=engine_runner,
                )

        assignment.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(assignment.status, WorkerTestAssignment.Status.PASSED)
        self.assertEqual(assignment.changed_files, ["app.py"])
        self.assertEqual(assignment.pull_request_number, 7)
        self.assertEqual(self.worker.status, WorkerAgent.Status.ACTIVE)
        self.assertTrue(self.worker.test_assignment_passed)
        self.assertFalse(self.worker.discovery_enabled)
        self.assertEqual(result.pull_request_number, 7)


class WorkerTestAssignmentHelperTests(TestCase):
    def test_git_auth_environment_disables_interactive_credential_manager(self):
        with _git_auth_environment(
            username="logicbloomlab",
            token="test-token",
        ) as environment:
            self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(environment["GIT_ASKPASS_REQUIRE"], "force")
            self.assertEqual(environment["GCM_INTERACTIVE"], "Never")
            self.assertEqual(environment["GCM_GUI_PROMPT"], "0")
            self.assertEqual(environment["GIT_CONFIG_COUNT"], "2")
            self.assertEqual(environment["GIT_CONFIG_KEY_0"], "credential.helper")
            self.assertEqual(environment["GIT_CONFIG_VALUE_0"], "")
            self.assertEqual(environment["GIT_CONFIG_KEY_1"], "core.askPass")
            self.assertEqual(
                environment["GIT_CONFIG_VALUE_1"],
                environment["GIT_ASKPASS"],
            )
            self.assertEqual(environment["VEYRA_GIT_USERNAME"], "logicbloomlab")
            self.assertEqual(environment["VEYRA_GIT_TOKEN"], "test-token")
            self.assertNotIn("test-token", environment["GIT_ASKPASS"])

    def test_noninteractive_git_credential_preflight_uses_temporary_helper(self):
        verify_noninteractive_git_credentials(
            username="logicbloomlab",
            token="test-token",
        )

    def test_run_command_replaces_invalid_utf8_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = _run_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(bytes([0x90]))",
                ],
                cwd=Path(temp_dir),
                timeout=30,
            )

        self.assertEqual(result.return_code, 0)
        self.assertIn("\ufffd", result.stdout)

    def test_extract_acceptance_criteria(self):
        body = """
## Acceptance Criteria
- [ ] Add `/health`
- Return JSON
1. Add tests

## Notes
Ignore this
"""
        self.assertEqual(
            _extract_acceptance_criteria(body),
            ("Add `/health`", "Return JSON", "Add tests"),
        )

    @patch.dict(
        os.environ,
        {"WORKER_TEST_ENGINE_ARGS": '["run", "--model", "{model}"]'},
        clear=False,
    )
    def test_engine_args_are_explicit_json(self):
        self.assertEqual(
            _engine_args("zai-org/glm-5.2"),
            ["run", "--model", "zai-org/glm-5.2"],
        )

    def test_validate_changed_files_rejects_env_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
            (workspace / ".env").write_text("SECRET=value", encoding="utf-8")

            with self.assertRaises(WorkerTestAssignmentError) as context:
                _validate_changed_files(workspace, [".env"])

            self.assertEqual(context.exception.stage, "validate_changes")

    def test_validate_changed_files_accepts_small_text_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=workspace,
                check=True,
            )
            app = workspace / "app.py"
            app.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=workspace, check=True, capture_output=True)
            app.write_text("value = 2\n", encoding="utf-8")

            _validate_changed_files(workspace, ["app.py"])


class WorkerTestAssignmentCommandTests(TestCase):
    def setUp(self):
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            owner_type=WorkerAgent.OwnerType.VEYRA,
            status=WorkerAgent.Status.TESTING,
            skills=["Python"],
            engine_provider=WorkerAgent.EngineProvider.OPENCODE,
            engine_model="zai-org/glm-5.2",
            engine_connected=True,
            engine_version="1.17.18",
            engine_last_checked_at=timezone.now(),
            circle_wallet_id="wallet-id",
            circle_wallet_set_id="wallet-set-id",
            worker_wallet_address="0x7e1efab63cb37b0550c9cf23d81622b66a31ea33",
            payout_wallet_address="0x7e1efab63cb37b0550c9cf23d81622b66a31ea33",
            github_username="logicbloomlab",
            github_connected=True,
            contract_authorised=True,
        )

    @patch(
        "workers.management.commands.prepare_worker_test_assignment."
        "prepare_controlled_test_assignment"
    )
    def test_prepare_command_reports_assignment(self, prepare):
        prepare.return_value = WorkerTestAssignment.objects.create(
            worker=self.worker,
            issue_url=(
                "https://github.com/sparexonzy95/veyra-agent-test-api/issues/1"
            ),
            repository_url=(
                "https://github.com/sparexonzy95/veyra-agent-test-api"
            ),
            source_owner="sparexonzy95",
            source_repository="veyra-agent-test-api",
            issue_number=1,
            issue_title="Test issue",
            base_branch="main",
            branch_name="veyra/test-issue-1-12345678",
            workspace_name="workspace",
        )

        call_command("prepare_worker_test_assignment")
        prepare.assert_called_once()

    def test_run_command_requires_prepared_assignment(self):
        with self.assertRaises(CommandError):
            call_command("run_worker_test_assignment")
