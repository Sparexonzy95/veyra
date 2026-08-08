from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from workers.hosted_agent_connection import runtime_is_online
from workers.models import (
    HostedAgentConnection,
    WorkerAgent,
    WorkerQualificationRun,
)


LEASE_SALT = "veyra.automatic-qualification.lease.v1"
QUALIFICATION_SPECS: dict[str, dict[str, Any]] = {
    "python": {
        "version": "python-health-v2",
        "title": "Veyra automatic Python qualification",
        "target_path": "src/service.py",
        "starter": '''def health_response():
    raise NotImplementedError("Complete the controlled qualification task")
''',
        "expected": '''def health_response():
    return {"status": "ok", "service": "veyra-qualification", "version": 1}
''',
        "support_files": [
            {"path": "src/__init__.py", "content": ""},
            {
                "path": "tests/test_visible.py",
                "content": '''from src.service import health_response


def test_health_response():
    assert health_response() == {
        "status": "ok",
        "service": "veyra-qualification",
        "version": 1,
    }
''',
            },
        ],
        "test_command": "python -m pytest -q",
    },
    "javascript": {
        "version": "javascript-health-v1",
        "title": "Veyra automatic JavaScript qualification",
        "target_path": "src/index.js",
        "starter": '''function healthResponse() {
  throw new Error("Complete the controlled qualification task");
}

module.exports = { healthResponse };
''',
        "expected": '''function healthResponse() {
  return { status: "ok", service: "veyra-qualification", version: 1 };
}

module.exports = { healthResponse };
''',
        "support_files": [
            {
                "path": "tests/health.test.js",
                "content": '''const assert = require("node:assert/strict");
const test = require("node:test");
const { healthResponse } = require("../src/index.js");

test("returns the qualification payload", () => {
  assert.deepEqual(healthResponse(), {
    status: "ok",
    service: "veyra-qualification",
    version: 1,
  });
});
''',
            },
        ],
        "test_command": "node --test tests/health.test.js",
    },
    "rust": {
        "version": "rust-health-v1",
        "title": "Veyra automatic Rust qualification",
        "target_path": "src/lib.rs",
        "starter": '''pub fn health_response() -> &'static str {
    todo!("Complete the controlled qualification task")
}
''',
        "expected": '''pub fn health_response() -> &'static str {
    "ok:veyra-qualification:1"
}
''',
        "support_files": [
            {
                "path": "Cargo.toml",
                "content": '''[package]
name = "veyra-qualification"
version = "0.1.0"
edition = "2021"
''',
            },
            {
                "path": "tests/health.rs",
                "content": '''use veyra_qualification::health_response;

#[test]
fn returns_the_qualification_payload() {
    assert_eq!(health_response(), "ok:veyra-qualification:1");
}
''',
            },
        ],
        "test_command": "cargo test --quiet",
    },
    "go": {
        "version": "go-health-v1",
        "title": "Veyra automatic Go qualification",
        "target_path": "cmd/api/main.go",
        "starter": '''package main

func healthResponse() string {
	panic("complete the controlled qualification task")
}
''',
        "expected": '''package main

func healthResponse() string {
	return "ok:veyra-qualification:1"
}
''',
        "support_files": [
            {"path": "go.mod", "content": "module veyra-qualification\n\ngo 1.22\n"},
            {
                "path": "cmd/api/main_test.go",
                "content": '''package main

import "testing"

func TestHealthResponse(t *testing.T) {
	if healthResponse() != "ok:veyra-qualification:1" {
		t.Fatal("unexpected qualification payload")
	}
}
''',
            },
        ],
        "test_command": "go test ./...",
    },
    "solidity": {
        "version": "solidity-foundry-health-v1",
        "title": "Veyra automatic Solidity qualification",
        "target_path": "src/Example.sol",
        "starter": '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Example {
    function healthResponse() external pure returns (string memory) {
        revert("Complete the controlled qualification task");
    }
}
''',
        "expected": '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Example {
    function healthResponse() external pure returns (string memory) {
        return "ok:veyra-qualification:1";
    }
}
''',
        "support_files": [
            {"path": "foundry.toml", "content": "[profile.default]\nsrc = 'src'\ntest = 'test'\n"},
            {
                "path": "test/Example.t.sol",
                "content": '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Example} from "../src/Example.sol";

contract ExampleTest {
    function testHealthResponse() public {
        Example example = new Example();
        require(
            keccak256(bytes(example.healthResponse())) ==
                keccak256(bytes("ok:veyra-qualification:1")),
            "unexpected qualification payload"
        );
    }
}
''',
            },
        ],
        "test_command": "forge test --quiet",
    },
}

QUALIFICATION_LANGUAGE_ALIASES = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "rust": "rust",
    "go": "go",
    "golang": "go",
    "solidity": "solidity",
    "foundry": "solidity",
    "hardhat": "solidity",
}


class AutomaticQualificationError(RuntimeError):
    pass


def _max_attempts() -> int:
    return max(1, int(getattr(settings, "VEYRA_QUALIFICATION_MAX_ATTEMPTS", 2)))


def _lease_minutes() -> int:
    return max(2, int(getattr(settings, "VEYRA_QUALIFICATION_LEASE_MINUTES", 15)))


def _safe_text(value: Any, *, limit: int = 2000) -> str:
    text = str(value or "").strip()
    for secret in (
        str(getattr(settings, "CIRCLE_API_KEY", "") or ""),
        str(getattr(settings, "CIRCLE_ENTITY_SECRET", "") or ""),
        str(getattr(settings, "DEPLOYER_PRIVATE_KEY", "") or ""),
        str(getattr(settings, "DJANGO_SECRET_KEY", "") or ""),
    ):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:limit]


def _b64url_decode(value: str) -> bytes:
    raw = str(value or "").strip()
    padding = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw + padding)
    except Exception as exc:
        raise AutomaticQualificationError(
            "The hosted runtime signing key is invalid."
        ) from exc


def _controlled_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/")
    if (
        not path
        or "\x00" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
    ):
        raise AutomaticQualificationError("The qualification target path is unsafe.")
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        raise AutomaticQualificationError("The qualification target path is unsafe.")
    normalized = "/".join(parts)
    lower_parts = [part.casefold() for part in parts]
    basename = lower_parts[-1]
    if (
        basename == ".env"
        or basename.startswith(".env.")
        or ".git" in lower_parts
        or lower_parts[:2] == [".github", "workflows"]
    ):
        raise AutomaticQualificationError("The qualification target path is protected.")
    return normalized


def _qualification_spec_for_worker(worker: WorkerAgent) -> dict[str, Any]:
    declared = [*list(worker.languages or []), *list(worker.skills or [])]
    for value in declared:
        key = re.sub(r"[^a-z0-9]+", "", str(value).casefold())
        spec_name = QUALIFICATION_LANGUAGE_ALIASES.get(key)
        if spec_name:
            return QUALIFICATION_SPECS[spec_name]
    raise AutomaticQualificationError(
        "No controlled qualification is configured for this agent's declared languages."
    )


def _qualification_spec_for_run(run: WorkerQualificationRun) -> dict[str, Any]:
    for spec in QUALIFICATION_SPECS.values():
        if spec["version"] == run.task_version:
            return spec
    raise AutomaticQualificationError("The qualification task version is unsupported.")


def _canonical_files(
    files: list[dict[str, str]],
    *,
    target_path: str,
) -> tuple[list[dict[str, str]], str]:
    controlled_target = _controlled_path(target_path)
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise AutomaticQualificationError("The qualification result contains an invalid file.")
        path = _controlled_path(item.get("path"))
        content = str(item.get("content") or "")
        if path != controlled_target or path.casefold() in seen:
            raise AutomaticQualificationError(
                f"Qualification may submit only {controlled_target}."
            )
        if len(content.encode("utf-8")) > 20_000:
            raise AutomaticQualificationError("The submitted qualification file is too large.")
        seen.add(path.casefold())
        cleaned.append({"path": path, "content": content})
    if [item["path"] for item in cleaned] != [controlled_target]:
        raise AutomaticQualificationError(
            f"The qualification result must include {controlled_target} only."
        )
    canonical = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return cleaned, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _signature_message(*, run_id: str, files_hash: str, test_return_code: int) -> bytes:
    return (
        f"veyra-qualification-v1:{run_id}:{files_hash}:{int(test_return_code)}"
    ).encode("utf-8")


def _verify_runtime_signature(
    connection: HostedAgentConnection,
    *,
    run_id: str,
    files_hash: str,
    test_return_code: int,
    signature_text: str,
) -> None:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            _b64url_decode(connection.public_key)
        )
        public_key.verify(
            _b64url_decode(signature_text),
            _signature_message(
                run_id=run_id,
                files_hash=files_hash,
                test_return_code=test_return_code,
            ),
        )
    except (ValueError, InvalidSignature) as exc:
        raise AutomaticQualificationError(
            "The qualification result signature is invalid."
        ) from exc


def _verify_controlled_solution(source: str, *, expected: str) -> None:
    def normalized(value: str) -> str:
        return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").strip().split("\n"))

    if normalized(source) != normalized(expected):
        raise AutomaticQualificationError(
            "The qualification solution does not match the controlled expected result."
        )


def _lease_token(run: WorkerQualificationRun) -> str:
    return signing.dumps(
        {
            "run_id": str(run.id),
            "worker_id": str(run.worker_id),
            "attempt": run.attempt_number,
        },
        salt=LEASE_SALT,
        compress=True,
    )


def _verify_lease_token(run: WorkerQualificationRun, token: str) -> None:
    try:
        payload = signing.loads(
            token,
            salt=LEASE_SALT,
            max_age=_lease_minutes() * 60 + 60,
        )
    except signing.BadSignature as exc:
        raise AutomaticQualificationError(
            "The qualification lease is invalid or expired."
        ) from exc
    if (
        str(payload.get("run_id") or "") != str(run.id)
        or str(payload.get("worker_id") or "") != str(run.worker_id)
        or int(payload.get("attempt") or 0) != run.attempt_number
    ):
        raise AutomaticQualificationError("The qualification lease does not match this agent.")
    if run.lease_expires_at and run.lease_expires_at < timezone.now():
        raise AutomaticQualificationError("The qualification lease expired.")


def ensure_automatic_qualification(worker: WorkerAgent) -> WorkerQualificationRun | None:
    worker.refresh_from_db()
    if worker.test_assignment_passed or worker.status == WorkerAgent.Status.ACTIVE:
        return None
    if not worker.contract_authorised or not worker.worker_wallet_address:
        return None
    try:
        connection = worker.hosted_connection
    except HostedAgentConnection.DoesNotExist:
        return None
    if not connection.provider_ready or not runtime_is_online(connection):
        return None

    active = WorkerQualificationRun.objects.filter(
        worker=worker,
        status__in=[
            WorkerQualificationRun.Status.QUEUED,
            WorkerQualificationRun.Status.LEASED,
            WorkerQualificationRun.Status.SUBMITTED,
        ],
    ).order_by("-attempt_number").first()
    if active:
        return active

    attempts = WorkerQualificationRun.objects.filter(worker=worker).count()
    if attempts >= _max_attempts():
        worker.status = WorkerAgent.Status.READY_FOR_QUALIFICATION
        worker.provisioning_stage = "QUALIFICATION_FAILED"
        worker.provisioning_error = (
            "Automatic qualification did not pass. Review the hosted runtime and retry setup."
        )
        worker.save(
            update_fields=[
                "status",
                "provisioning_stage",
                "provisioning_error",
                "updated_at",
            ]
        )
        return None

    spec = _qualification_spec_for_worker(worker)
    run = WorkerQualificationRun.objects.create(
        worker=worker,
        attempt_number=attempts + 1,
        task_version=str(spec["version"]),
        status=WorkerQualificationRun.Status.QUEUED,
    )
    worker.status = WorkerAgent.Status.TESTING
    worker.provisioning_stage = "QUALIFICATION_QUEUED"
    worker.provisioning_error = ""
    worker.save(
        update_fields=[
            "status",
            "provisioning_stage",
            "provisioning_error",
            "updated_at",
        ]
    )
    return run


def qualification_task_for_connection(
    connection: HostedAgentConnection,
) -> dict[str, Any] | None:
    worker = connection.worker
    run = ensure_automatic_qualification(worker)
    if run is None:
        return None
    if run.status not in {
        WorkerQualificationRun.Status.QUEUED,
        WorkerQualificationRun.Status.LEASED,
    }:
        return None

    now = timezone.now()
    run.status = WorkerQualificationRun.Status.LEASED
    run.lease_expires_at = now + timedelta(minutes=_lease_minutes())
    if run.started_at is None:
        run.started_at = now
    run.save(
        update_fields=[
            "status",
            "lease_expires_at",
            "started_at",
            "updated_at",
        ]
    )

    if worker.status != WorkerAgent.Status.TESTING or worker.provisioning_stage != "QUALIFICATION_RUNNING":
        worker.status = WorkerAgent.Status.TESTING
        worker.provisioning_stage = "QUALIFICATION_RUNNING"
        worker.provisioning_error = ""
        worker.save(
            update_fields=[
                "status",
                "provisioning_stage",
                "provisioning_error",
                "updated_at",
            ]
        )

    spec = _qualification_spec_for_run(run)
    target_path = _controlled_path(spec["target_path"])
    expected = str(spec["expected"])
    instructions = (
        f"Replace only {target_path} with the exact controlled source below. "
        "Do not add imports, dependencies, network calls, file access, or subprocesses. "
        f"Run {spec['test_command']} before submitting.\n\n{expected}"
    )
    api_root = str(
        getattr(settings, "VEYRA_PUBLIC_API_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    return {
        "id": str(run.id),
        "type": "automatic_qualification",
        "attempt": run.attempt_number,
        "task_version": run.task_version,
        "title": str(spec["title"]),
        "instructions": instructions,
        "qualification_target_path": target_path,
        "starter_files": [
            {"path": target_path, "content": str(spec["starter"])},
            *list(spec["support_files"]),
        ],
        "allowed_submission_paths": [target_path],
        "test_command": str(spec["test_command"]),
        "lease_token": _lease_token(run),
        "submit_url": f"{api_root}/api/v1/agent-runtime/qualification/submit/",
    }


def _mark_failed(
    run: WorkerQualificationRun,
    *,
    message: str,
    runtime_metadata: dict[str, str] | None = None,
) -> WorkerQualificationRun:
    metadata = runtime_metadata or {}
    run.status = WorkerQualificationRun.Status.FAILED
    run.provider = str(metadata.get("provider") or "")[:80]
    run.model_name = str(metadata.get("model") or "")[:160]
    run.runtime_version = str(metadata.get("runtime_version") or "")[:64]
    run.failure_message = _safe_text(message)
    run.completed_at = timezone.now()
    run.save(
        update_fields=[
            "status",
            "provider",
            "model_name",
            "runtime_version",
            "failure_message",
            "completed_at",
            "updated_at",
        ]
    )
    worker = run.worker
    worker.status = WorkerAgent.Status.READY_FOR_QUALIFICATION
    worker.provisioning_stage = "QUALIFICATION_FAILED"
    worker.provisioning_error = run.failure_message
    worker.save(
        update_fields=[
            "status",
            "provisioning_stage",
            "provisioning_error",
            "updated_at",
        ]
    )
    return run


def submit_automatic_qualification(
    *,
    connection: HostedAgentConnection,
    payload: dict[str, Any],
) -> tuple[WorkerQualificationRun, bool]:
    run_id = str(payload.get("qualification_id") or "").strip()
    lease_token = str(payload.get("lease_token") or "").strip()
    if not run_id or not lease_token:
        raise AutomaticQualificationError("Qualification ID and lease token are required.")

    with transaction.atomic():
        run = (
            WorkerQualificationRun.objects.select_for_update()
            .select_related("worker")
            .filter(id=run_id, worker=connection.worker)
            .first()
        )
        if not run:
            raise AutomaticQualificationError("Qualification run was not found.")
        if run.status == WorkerQualificationRun.Status.PASSED:
            return run, True
        if run.status not in {
            WorkerQualificationRun.Status.LEASED,
            WorkerQualificationRun.Status.SUBMITTED,
        }:
            raise AutomaticQualificationError(
                f"Qualification is {run.status.lower()}, not ready for submission."
            )
        _verify_lease_token(run, lease_token)

        runtime_error = _safe_text(payload.get("runtime_error"), limit=1200)
        metadata = {
            "provider": str(payload.get("provider") or connection.provider),
            "model": str(payload.get("model") or connection.model_name),
            "runtime_version": str(
                payload.get("runtime_version") or connection.runtime_version
            ),
        }
        if runtime_error:
            _mark_failed(run, message=runtime_error, runtime_metadata=metadata)
            return run, False

        files_value = payload.get("files")
        if not isinstance(files_value, list):
            raise AutomaticQualificationError("Qualification files must be a list.")
        spec = _qualification_spec_for_run(run)
        files, files_hash = _canonical_files(
            files_value,
            target_path=str(spec["target_path"]),
        )
        try:
            test_return_code = int(payload.get("test_return_code"))
        except (TypeError, ValueError) as exc:
            raise AutomaticQualificationError(
                "Qualification test return code is invalid."
            ) from exc
        signature_text = str(payload.get("signature") or "").strip()
        _verify_runtime_signature(
            connection,
            run_id=str(run.id),
            files_hash=files_hash,
            test_return_code=test_return_code,
            signature_text=signature_text,
        )

        run.status = WorkerQualificationRun.Status.SUBMITTED
        run.submitted_at = timezone.now()
        run.provider = metadata["provider"][:80]
        run.model_name = metadata["model"][:160]
        run.runtime_version = metadata["runtime_version"][:64]
        run.submitted_files = files
        run.test_return_code = test_return_code
        run.test_output = _safe_text(payload.get("test_output"), limit=12000)
        run.result_signature = signature_text[:500]
        run.save(
            update_fields=[
                "status",
                "submitted_at",
                "provider",
                "model_name",
                "runtime_version",
                "submitted_files",
                "test_return_code",
                "test_output",
                "result_signature",
                "updated_at",
            ]
        )

        if test_return_code != 0:
            _mark_failed(
                run,
                message="The hosted runtime's visible qualification tests failed.",
                runtime_metadata=metadata,
            )
            return run, False

        try:
            _verify_controlled_solution(
                files[0]["content"],
                expected=str(spec["expected"]),
            )
        except AutomaticQualificationError as exc:
            _mark_failed(run, message=str(exc), runtime_metadata=metadata)
            return run, False

        run.status = WorkerQualificationRun.Status.PASSED
        run.failure_message = ""
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "failure_message",
                "completed_at",
                "updated_at",
            ]
        )

        worker = run.worker
        worker.test_assignment_passed = True
        worker.status = WorkerAgent.Status.ACTIVE
        worker.provisioning_stage = "ACTIVE"
        worker.provisioning_error = ""
        worker.auto_claim_enabled = True
        worker.discovery_enabled = True
        if worker.activated_at is None:
            worker.activated_at = timezone.now()
        worker.save(
            update_fields=[
                "test_assignment_passed",
                "status",
                "provisioning_stage",
                "provisioning_error",
                "auto_claim_enabled",
                "discovery_enabled",
                "activated_at",
                "updated_at",
            ]
        )
        return run, True
