from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from django.conf import settings
from django.utils import timezone
from web3 import Web3

from blockchain.client import ArcClient
from workers.engine import EngineHealthResult, check_opencode_engine
from workers.github_bot import GitHubBotConnectionResult, check_github_bot
from workers.models import WorkerAgent


class WorkerReadinessError(RuntimeError):
    """Raised when a worker cannot be safely synchronized or tested."""


@dataclass(frozen=True)
class ContractAuthorisationResult:
    authorised: bool
    contract_paused: bool
    verifier_authorised: bool
    chain_id: int
    contract_address: str
    worker_address: str
    verifier_address: str
    checked_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerReadinessResult:
    ready: bool
    worker_id: str
    status: str
    checks: tuple[ReadinessCheck, ...]
    checked_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "worker_id": self.worker_id,
            "status": self.status,
            "checks": [check.as_dict() for check in self.checks],
            "checked_at": self.checked_at,
        }


def _normalise_address(value: str) -> str:
    text = str(value or "").strip()
    if not Web3.is_address(text):
        raise WorkerReadinessError(f"Invalid EVM address: {text or '[missing]'}")
    return Web3.to_checksum_address(text)


def _safe_error(exc: Exception) -> str:
    text = str(exc or "").strip()
    if len(text) > 600:
        return text[:600] + "…"
    return text or exc.__class__.__name__


def sync_worker_contract_authorisation(
    worker: WorkerAgent,
    *,
    arc_client: ArcClient | None = None,
) -> ContractAuthorisationResult:
    """Read authoritative contract state from Arc and store the worker flag.

    This function never submits a transaction. It only performs view calls.
    """

    worker.refresh_from_db()

    if not worker.worker_wallet_address:
        raise WorkerReadinessError("The worker wallet address is missing.")

    worker_address = _normalise_address(worker.worker_wallet_address)
    verifier_address = _normalise_address(settings.VEYRA_VERIFIER_ADDRESS)
    client = arc_client or ArcClient()

    try:
        actual_chain_id = client.assert_chain()
        chain_id = int(
            actual_chain_id
            if actual_chain_id is not None
            else settings.ARC_CHAIN_ID
        )
        contract_paused = bool(client.is_paused())
        authorised = bool(client.is_agent_authorised(worker_address))
        verifier_authorised = bool(client.is_verifier_authorised(verifier_address))
    except WorkerReadinessError:
        raise
    except Exception as exc:
        raise WorkerReadinessError(
            f"Could not read Veyra contract authorisation from Arc: {_safe_error(exc)}"
        ) from exc

    worker.contract_authorised = authorised

    if authorised:
        if worker.status == WorkerAgent.Status.AUTHORISATION_PENDING:
            worker.status = WorkerAgent.Status.GITHUB_READY
    else:
        if worker.status not in {
            WorkerAgent.Status.SETUP_REQUIRED,
            WorkerAgent.Status.PROFILE_READY,
            WorkerAgent.Status.ENGINE_CONNECTED,
            WorkerAgent.Status.WALLET_READY,
            WorkerAgent.Status.PAYOUT_READY,
        }:
            worker.status = WorkerAgent.Status.AUTHORISATION_PENDING

    worker.save(
        update_fields=[
            "contract_authorised",
            "status",
            "discovery_enabled",
            "updated_at",
        ]
    )

    contract_address = str(
        getattr(getattr(client, "contract", None), "address", settings.VEYRA_CONTRACT_ADDRESS)
    )

    return ContractAuthorisationResult(
        authorised=authorised,
        contract_paused=contract_paused,
        verifier_authorised=verifier_authorised,
        chain_id=chain_id,
        contract_address=contract_address,
        worker_address=worker_address,
        verifier_address=verifier_address,
        checked_at=timezone.now().isoformat(),
    )


def _check(name: str, passed: bool, success: str, failure: str) -> ReadinessCheck:
    return ReadinessCheck(
        name=name,
        passed=bool(passed),
        detail=success if passed else failure,
    )


def check_worker_readiness(
    worker: WorkerAgent,
    *,
    arc_client: ArcClient | None = None,
    engine_checker: Callable[[WorkerAgent], EngineHealthResult] = check_opencode_engine,
    github_checker: Callable[..., GitHubBotConnectionResult] = check_github_bot,
) -> WorkerReadinessResult:
    """Run live worker checks before the first test assignment.

    Passing this gate moves the worker to TESTING. It does not enable discovery,
    mark the test assignment as passed, or activate the worker.
    """

    worker.refresh_from_db()
    checks: list[ReadinessCheck] = []

    profile_ready = bool(worker.name.strip() and worker.slug and worker.skills)
    checks.append(
        _check(
            "profile",
            profile_ready,
            "Worker profile and skills are configured.",
            "Worker profile or skills are incomplete.",
        )
    )

    checks.append(
        _check(
            "engine_record",
            worker.engine_connected,
            f"Stored engine connection is {worker.engine_provider} / {worker.engine_model}.",
            "The worker engine is not marked connected.",
        )
    )

    try:
        engine_result = engine_checker(worker)
        checks.append(
            _check(
                "engine_live",
                engine_result.connected,
                f"OpenCode is reachable ({engine_result.version}).",
                engine_result.message,
            )
        )
    except Exception as exc:
        checks.append(
            ReadinessCheck(
                name="engine_live",
                passed=False,
                detail=f"Engine health check failed: {_safe_error(exc)}",
            )
        )

    wallet_ready = bool(
        worker.circle_wallet_id
        and worker.circle_wallet_set_id
        and worker.worker_wallet_address
        and worker.wallet_blockchain == "ARC-TESTNET"
        and worker.wallet_account_type == "SCA"
    )
    checks.append(
        _check(
            "worker_wallet",
            wallet_ready,
            f"Circle SCA wallet is configured on {worker.wallet_blockchain}.",
            "Circle worker wallet metadata is incomplete or uses the wrong network/account type.",
        )
    )

    payout_ready = bool(worker.payout_wallet_address)
    checks.append(
        _check(
            "payout_wallet",
            payout_ready,
            "Worker payout wallet is configured.",
            "Worker payout wallet is missing.",
        )
    )

    try:
        github_result = github_checker()
        checks.append(
            _check(
                "github_platform",
                github_result.connected,
                f"Veyra GitHub qualification service is authenticated as {github_result.login}.",
                "Veyra GitHub qualification service is unavailable.",
            )
        )
    except Exception as exc:
        checks.append(
            ReadinessCheck(
                name="github_platform",
                passed=False,
                detail=f"Veyra GitHub qualification check failed: {_safe_error(exc)}",
            )
        )

    try:
        contract_result = sync_worker_contract_authorisation(
            worker,
            arc_client=arc_client,
        )
        checks.extend(
            [
                _check(
                    "arc_chain",
                    contract_result.chain_id == settings.ARC_CHAIN_ID,
                    f"Arc chain ID is {contract_result.chain_id}.",
                    (
                        f"Arc chain mismatch: expected {settings.ARC_CHAIN_ID}, "
                        f"got {contract_result.chain_id}."
                    ),
                ),
                _check(
                    "escrow_unpaused",
                    not contract_result.contract_paused,
                    "Veyra escrow contract is not paused.",
                    "Veyra escrow contract is paused.",
                ),
                _check(
                    "agent_authorised",
                    contract_result.authorised,
                    "Worker wallet is authorised by the escrow contract.",
                    "Worker wallet is not authorised by the escrow contract.",
                ),
                _check(
                    "verifier_authorised",
                    contract_result.verifier_authorised,
                    "Verifier wallet is authorised by the escrow contract.",
                    "Verifier wallet is not authorised by the escrow contract.",
                ),
            ]
        )
    except Exception as exc:
        checks.append(
            ReadinessCheck(
                name="contract_state",
                passed=False,
                detail=f"Arc contract check failed: {_safe_error(exc)}",
            )
        )

    ready = all(check.passed for check in checks)

    worker.refresh_from_db()
    if ready:
        worker.status = WorkerAgent.Status.TESTING
        worker.discovery_enabled = False
        worker.save(
            update_fields=[
                "status",
                "discovery_enabled",
                "updated_at",
            ]
        )

    return WorkerReadinessResult(
        ready=ready,
        worker_id=str(worker.id),
        status=worker.status,
        checks=tuple(checks),
        checked_at=timezone.now().isoformat(),
    )
