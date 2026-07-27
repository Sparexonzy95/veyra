from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from workers.circle_wallet import WorkerWalletProvisioningError, provision_worker_wallet
from workers.contract_authorisation import (
    ContractAuthorisationError,
    ContractAuthorisationPending,
    authorise_worker_contract,
)
from workers.hosted_agent_connection import (
    HostedAgentConnectionError,
    connect_hosted_agent,
)
from workers.models import HostedAgentConnection, WorkerAgent


class AgentProvisioningError(RuntimeError):
    """Safe provisioning failure already persisted on the agent profile."""


@dataclass(frozen=True)
class AgentProvisioningResult:
    agent_id: str
    status: str
    stage: str
    runtime_connected: bool
    wallet_ready: bool
    contract_authorised: bool


def _safe_message(exc: Exception) -> str:
    return (str(exc or "").strip() or exc.__class__.__name__)[:800]


def _set_stage(
    worker: WorkerAgent,
    *,
    stage: str,
    status_value: str | None = None,
    error: str = "",
) -> WorkerAgent:
    with transaction.atomic():
        locked = WorkerAgent.objects.select_for_update().get(pk=worker.pk)
        locked.provisioning_stage = stage
        locked.provisioning_error = error
        if status_value:
            locked.status = status_value
        locked.save(
            update_fields=[
                "provisioning_stage",
                "provisioning_error",
                "status",
                "updated_at",
            ]
        )
    worker.refresh_from_db()
    return worker


def _runtime_ready(worker: WorkerAgent) -> bool:
    try:
        connection = worker.hosted_connection
    except HostedAgentConnection.DoesNotExist:
        return False
    return bool(
        connection.status == HostedAgentConnection.Status.CONNECTED
        and connection.provider_ready
        and worker.engine_connected
    )


def provision_agent(
    worker: WorkerAgent,
    *,
    connection_link: str | None = None,
) -> AgentProvisioningResult:
    """One-click, retry-safe owner-hosted agent provisioning.

    This function intentionally performs the automated steps in order. It never
    stores the one-time connection token or the owner's AI provider key.
    """

    worker.refresh_from_db()
    _set_stage(
        worker,
        stage="VERIFYING_RUNTIME",
        status_value=WorkerAgent.Status.PROVISIONING,
    )

    if not _runtime_ready(worker):
        if not str(connection_link or "").strip():
            message = "Paste a fresh connection link from the hosted-agent server."
            _set_stage(
                worker,
                stage="RUNTIME_VERIFICATION_FAILED",
                status_value=WorkerAgent.Status.RUNTIME_VERIFICATION_FAILED,
                error=message,
            )
            raise AgentProvisioningError(message)
        try:
            connect_hosted_agent(worker=worker, connection_link=str(connection_link))
        except HostedAgentConnectionError as exc:
            message = _safe_message(exc)
            failure_status = (
                WorkerAgent.Status.PROVIDER_UNAVAILABLE
                if "provider" in message.lower() or "api key" in message.lower()
                else WorkerAgent.Status.RUNTIME_VERIFICATION_FAILED
            )
            _set_stage(
                worker,
                stage=failure_status,
                status_value=failure_status,
                error=message,
            )
            raise AgentProvisioningError(message) from exc

    worker.refresh_from_db()
    _set_stage(
        worker,
        stage="CREATING_WALLET",
        status_value=WorkerAgent.Status.PROVISIONING,
    )
    try:
        provision_worker_wallet(worker)
    except WorkerWalletProvisioningError as exc:
        message = _safe_message(exc)
        _set_stage(
            worker,
            stage="WALLET_CREATION_FAILED",
            status_value=WorkerAgent.Status.WALLET_CREATION_FAILED,
            error=message,
        )
        raise AgentProvisioningError(message) from exc

    worker.refresh_from_db()
    _set_stage(
        worker,
        stage="AUTHORIZING_CONTRACT",
        status_value=WorkerAgent.Status.AUTHORISATION_PENDING,
    )
    try:
        authorise_worker_contract(worker)
    except ContractAuthorisationPending as exc:
        message = _safe_message(exc)
        _set_stage(
            worker,
            stage="AUTHORIZING_CONTRACT",
            status_value=WorkerAgent.Status.AUTHORISATION_PENDING,
            error=message,
        )
        raise AgentProvisioningError(message) from exc
    except ContractAuthorisationError as exc:
        message = _safe_message(exc)
        _set_stage(
            worker,
            stage="CONTRACT_AUTHORISATION_FAILED",
            status_value=WorkerAgent.Status.CONTRACT_AUTHORISATION_FAILED,
            error=message,
        )
        raise AgentProvisioningError(message) from exc

    worker.refresh_from_db()
    final_status = (
        WorkerAgent.Status.ACTIVE
        if worker.test_assignment_passed
        else WorkerAgent.Status.READY_FOR_QUALIFICATION
    )
    _set_stage(
        worker,
        stage="READY_FOR_QUALIFICATION" if not worker.test_assignment_passed else "ACTIVE",
        status_value=final_status,
        error="",
    )
    worker.refresh_from_db()

    return AgentProvisioningResult(
        agent_id=str(worker.id),
        status=worker.status,
        stage=worker.provisioning_stage,
        runtime_connected=_runtime_ready(worker),
        wallet_ready=bool(worker.circle_wallet_id and worker.worker_wallet_address),
        contract_authorised=worker.contract_authorised,
    )
