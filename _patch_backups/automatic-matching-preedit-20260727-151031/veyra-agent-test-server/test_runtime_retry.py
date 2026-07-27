from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _FakeThread:
    created = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True


class RuntimeRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["VEYRA_RUNTIME_STATE_DIR"] = cls.temp_dir.name
        os.environ["AI_HEALTHCHECK_MODE"] = "mock"
        source = Path(__file__).resolve().parent / "server.py"
        spec = importlib.util.spec_from_file_location("veyra_test_runtime_server", source)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        cls.server = module

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.server.JOB_RUNNING.clear()
        _FakeThread.created.clear()

    def test_new_lease_retries_same_assignment_after_failure(self):
        failed_state = self.server.default_state()
        failed_state.update(
            {
                "job_assignment_id": "assignment-1",
                "job_lease_id": "old-lease",
                "job_status": "failed",
            }
        )
        old_task = {"id": "assignment-1", "lease_id": "old-lease"}
        new_task = {"id": "assignment-1", "lease_id": "new-lease"}

        with (
            patch.object(self.server, "load_state", return_value=failed_state),
            patch.object(self.server.threading, "Thread", _FakeThread),
        ):
            self.server.ensure_job_thread(old_task)
            self.assertEqual(_FakeThread.created, [])

            self.server.ensure_job_thread(new_task)
            self.assertEqual(len(_FakeThread.created), 1)
            self.assertTrue(_FakeThread.created[0].started)
            self.assertIn("assignment-1:new-lease", self.server.JOB_RUNNING)

    def test_task_without_lease_is_not_started(self):
        with patch.object(self.server.threading, "Thread", _FakeThread):
            self.server.ensure_job_thread({"id": "assignment-1", "lease_id": ""})
        self.assertEqual(_FakeThread.created, [])


if __name__ == "__main__":
    unittest.main()
