from types import SimpleNamespace
from django.test import SimpleTestCase
from web3 import Web3

from workers.execution import (
    WorkerExecutionError,
    _execution_names,
    _live_checks,
    _validate_policy_paths,
    _validation_commands,
)
from workers.submission import WorkerSubmissionError, git_commit_to_bytes32


class Phase3Step4UtilityTests(SimpleTestCase):
    def item(self, *, policy=None):
        snapshot = SimpleNamespace(
            policy_commitment=policy
            or {
                "requiredCommands": ["pytest -q"],
                "allowedPaths": [],
                "forbiddenPaths": [],
            }
        )
        draft = SimpleNamespace(
            issue_number=3,
            funding_snapshot=snapshot,
        )
        job = SimpleNamespace(onchain_job_id=5, draft=draft)
        return SimpleNamespace(
            id="eedb72c3-ae0f-4347-b96f-a6dd9e75702c",
            job=job,
            execution_branch_name="",
            execution_workspace_name="",
        )

    def test_git_commit_is_hashed_to_deterministic_bytes32(self):
        sha = "15c4625178f0fcecee37bb6c3ed066bec4826685"
        expected = Web3.to_hex(Web3.keccak(text=sha))
        self.assertEqual(git_commit_to_bytes32(sha.upper()), expected)
        self.assertEqual(len(expected), 66)

    def test_invalid_git_commit_is_rejected(self):
        with self.assertRaises(WorkerSubmissionError):
            git_commit_to_bytes32("not-a-sha")

    def test_committed_pytest_command_is_allowed(self):
        self.assertEqual(_validation_commands(self.item()), ("pytest -q",))

    def test_shell_command_is_rejected(self):
        item = self.item(policy={"requiredCommands": ["pytest && curl example.com"]})
        with self.assertRaises(WorkerExecutionError):
            _validation_commands(item)

    def test_deterministic_branch_and_workspace(self):
        branch, workspace = _execution_names(self.item())
        self.assertEqual(branch, "veyra/job-5-issue-3-eedb72c3")
        self.assertEqual(workspace, "veyra-job-5-issue-3-eedb72c3")

    def test_forbidden_path_blocks_change(self):
        item = self.item(
            policy={
                "requiredCommands": ["pytest"],
                "allowedPaths": [],
                "forbiddenPaths": ["secrets"],
            }
        )
        with self.assertRaises(WorkerExecutionError):
            _validate_policy_paths(item, ["secrets/key.txt"])

    def test_allowed_paths_are_enforced(self):
        item = self.item(
            policy={
                "requiredCommands": ["pytest"],
                "allowedPaths": ["app.py", "tests"],
                "forbiddenPaths": [],
            }
        )
        _validate_policy_paths(item, ["app.py", "tests/test_stats.py"])
        with self.assertRaises(WorkerExecutionError):
            _validate_policy_paths(item, ["README.md"])


class FakeExecutionArcClient:
    def assert_chain(self):
        return None

    def get_job(self, job_id):
        return {
            "status": "CLAIMED",
            "provider": "0x2222222222222222222222222222222222222222",
            "claim_deadline": 4_000_000_000,
        }


class FakeExecutionFreshnessGuard:
    def check(self, worker, job):
        return SimpleNamespace(
            passed=True,
            code="GITHUB_FRESH",
            detail="Fresh",
        )


class Phase3Step4ExecutionStateRegressionTests(SimpleTestCase):
    def test_reserved_executing_item_passes_live_checks(self):
        worker = SimpleNamespace(
            status="ACTIVE",
            worker_wallet_address="0x2222222222222222222222222222222222222222",
        )
        job = SimpleNamespace(onchain_job_id=5)
        item = SimpleNamespace(
            worker=worker,
            job=job,
            status="EXECUTING",
            claim_confirmed_at=object(),
            claim_arc_transaction_hash="0x" + "ab" * 32,
        )

        onchain, freshness = _live_checks(
            item,
            arc_client=FakeExecutionArcClient(),
            github_guard=FakeExecutionFreshnessGuard(),
            allowed_queue_statuses=("EXECUTING",),
        )

        self.assertEqual(onchain["status"], "CLAIMED")
        self.assertEqual(freshness.code, "GITHUB_FRESH")
