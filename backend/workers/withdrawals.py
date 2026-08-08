from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from blockchain.client import ArcClient
from common.models import AuditLog
from wallets.models import WalletAccount
from workers.circle_wallet import EVM_ADDRESS_RE, _to_plain
from workers.capacity import ACTIVE_ASSIGNMENT_STATUSES
from workers.models import AgentWithdrawal, WorkerAgent


RESERVE_USDC = Decimal("0.050000")
TERMINAL_CIRCLE_STATES = {"COMPLETE", "FAILED", "CANCELLED", "DENIED"}
PENDING_WITHDRAWAL_STATES = {AgentWithdrawal.Status.SUBMITTING, AgentWithdrawal.Status.PENDING}


class AgentWithdrawalError(RuntimeError):
    pass


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _quantize(value: Decimal) -> Decimal:
    return max(value, Decimal("0")).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)


def _init_circle():
    api_key = str(getattr(settings, "CIRCLE_API_KEY", "") or "").strip()
    entity_secret = str(getattr(settings, "CIRCLE_ENTITY_SECRET", "") or "").strip()
    if not api_key or not entity_secret:
        raise AgentWithdrawalError("Circle developer wallet credentials are not configured.")
    try:
        from circle.web3 import developer_controlled_wallets, utils
    except ImportError as exc:
        raise AgentWithdrawalError("Circle developer-controlled wallet SDK is not installed.") from exc
    try:
        client = utils.init_developer_controlled_wallets_client(
            api_key=api_key,
            entity_secret=entity_secret,
        )
        return developer_controlled_wallets, client
    except Exception as exc:
        raise AgentWithdrawalError(f"Circle wallet client could not be initialized: {exc}") from exc


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _extract_usdc_balance(response: Any) -> Decimal:
    plain = _to_plain(response)
    expected = str(settings.ARC_USDC_ADDRESS).lower()
    fallback = None
    for mapping in _walk(plain):
        amount = mapping.get("amount")
        token = mapping.get("token")
        if amount is None or not isinstance(token, dict):
            continue
        address = str(
            token.get("tokenAddress")
            or token.get("token_address")
            or token.get("address")
            or ""
        ).lower()
        symbol = str(token.get("symbol") or "").upper()
        if address == expected:
            return _quantize(_decimal(amount))
        if symbol == "USDC" and fallback is None:
            fallback = _quantize(_decimal(amount))
    return fallback or Decimal("0.000000")


def read_worker_usdc_balance(worker: WorkerAgent) -> Decimal:
    if not worker.circle_wallet_id or not worker.worker_wallet_address:
        raise AgentWithdrawalError("This agent does not have a Circle operational wallet.")
    developer_controlled_wallets, client = _init_circle()
    try:
        wallets_api = developer_controlled_wallets.WalletsApi(client)
        response = wallets_api.list_wallet_balance(id=worker.circle_wallet_id)
        return _extract_usdc_balance(response)
    except Exception as exc:
        raise AgentWithdrawalError(f"Circle could not read the agent wallet balance: {exc}") from exc


def _extract_transfer(response: Any) -> tuple[str, str]:
    plain = _to_plain(response)
    for mapping in _walk(plain):
        identifier = str(mapping.get("id") or "").strip()
        state = str(mapping.get("state") or "").strip().upper()
        if identifier and state:
            return identifier, state
    raise AgentWithdrawalError("Circle did not return a transaction identifier for the withdrawal.")


def _extract_transaction(response: Any) -> dict[str, str]:
    plain = _to_plain(response)
    candidates = []
    for mapping in _walk(plain):
        identifier = str(mapping.get("id") or "").strip()
        state = str(mapping.get("state") or "").strip().upper()
        if identifier and state:
            candidates.append(mapping)
    if not candidates:
        raise AgentWithdrawalError("Circle returned no transaction state for this withdrawal.")
    mapping = candidates[-1]
    tx_hash = str(mapping.get("txHash") or mapping.get("tx_hash") or "").strip()
    return {
        "id": str(mapping.get("id") or ""),
        "state": str(mapping.get("state") or "").upper(),
        "tx_hash": tx_hash,
    }


def _circle_state_to_status(state: str) -> str:
    state = str(state or "").upper()
    if state == "COMPLETE":
        return AgentWithdrawal.Status.COMPLETED
    if state in {"FAILED", "CANCELLED", "DENIED"}:
        return AgentWithdrawal.Status.FAILED
    return AgentWithdrawal.Status.PENDING


def _receipt_status(receipt: Any) -> int | None:
    if receipt is None:
        return None
    value = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
    if value is None:
        return None
    try:
        if isinstance(value, str):
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        return int(value)
    except (TypeError, ValueError):
        return None


def _arc_status_for_hash(tx_hash: str, *, arc_client: ArcClient | None = None) -> str | None:
    normalized = str(tx_hash or "").strip()
    if not normalized:
        return None
    try:
        receipt = (arc_client or ArcClient()).transaction_receipt_or_none(normalized)
    except Exception:
        # Arc RPC failover/polling is best-effort here. Circle remains the
        # secondary reconciliation source and the next request will retry.
        return None
    status = _receipt_status(receipt)
    if status == 1:
        return AgentWithdrawal.Status.COMPLETED
    if status == 0:
        return AgentWithdrawal.Status.FAILED
    return None


def reconcile_withdrawal(
    withdrawal: AgentWithdrawal, *, arc_client: ArcClient | None = None
) -> AgentWithdrawal:
    if withdrawal.status not in PENDING_WITHDRAWAL_STATES or not withdrawal.circle_transaction_id:
        return withdrawal
    previous_status = withdrawal.status
    developer_controlled_wallets, client = _init_circle()
    try:
        transactions_api = developer_controlled_wallets.TransactionsApi(client)
        response = transactions_api.get_transaction(id=withdrawal.circle_transaction_id)
        tx = _extract_transaction(response)
    except Exception as exc:
        # Circle can lag behind Arc after broadcast. If we already know the
        # transaction hash, confirmed Arc receipt is the stronger source of
        # truth and lets the UI finish without waiting for Circle's projection.
        arc_status = _arc_status_for_hash(
            withdrawal.arc_transaction_hash, arc_client=arc_client
        )
        if arc_status is None:
            # A read failure must never cause a second transfer. Keep the
            # existing transaction authoritative and let the next read retry.
            withdrawal.failure_message = f"Withdrawal status could not be refreshed: {exc}"
            withdrawal.save(update_fields=["failure_message", "updated_at"])
            return withdrawal
        tx = {
            "id": withdrawal.circle_transaction_id,
            "state": "ARC_CONFIRMED" if arc_status == AgentWithdrawal.Status.COMPLETED else "ARC_REVERTED",
            "tx_hash": withdrawal.arc_transaction_hash,
        }
        withdrawal.status = arc_status
    else:
        withdrawal.arc_transaction_hash = tx["tx_hash"] or withdrawal.arc_transaction_hash
        arc_status = _arc_status_for_hash(
            withdrawal.arc_transaction_hash, arc_client=arc_client
        )
        withdrawal.status = arc_status or _circle_state_to_status(tx["state"])

    withdrawal.arc_transaction_hash = tx["tx_hash"] or withdrawal.arc_transaction_hash
    if withdrawal.status == AgentWithdrawal.Status.FAILED:
        withdrawal.failure_message = (
            "Arc withdrawal transaction reverted."
            if arc_status == AgentWithdrawal.Status.FAILED
            else f"Circle transaction ended in {tx['state']}."
        )
    else:
        withdrawal.failure_message = ""
    if withdrawal.status == AgentWithdrawal.Status.COMPLETED:
        withdrawal.completed_at = withdrawal.completed_at or timezone.now()
    withdrawal.save(
        update_fields=[
            "status", "arc_transaction_hash", "failure_message", "completed_at", "updated_at"
        ]
    )
    if previous_status != withdrawal.status and withdrawal.status in {
        AgentWithdrawal.Status.COMPLETED, AgentWithdrawal.Status.FAILED
    }:
        AuditLog.objects.create(
            actor=withdrawal.owner_user,
            action=(
                "AGENT_USDC_WITHDRAWAL_COMPLETED"
                if withdrawal.status == AgentWithdrawal.Status.COMPLETED
                else "AGENT_USDC_WITHDRAWAL_FAILED"
            ),
            resource_type="WorkerAgent",
            resource_id=str(withdrawal.worker_id),
            result="SUCCESS" if withdrawal.status == AgentWithdrawal.Status.COMPLETED else "FAILED",
            metadata={
                "withdrawal_id": str(withdrawal.id),
                "amount_usdc": str(withdrawal.amount_usdc),
                "destination_address": withdrawal.destination_address,
                "circle_transaction_id": withdrawal.circle_transaction_id,
                "arc_transaction_hash": withdrawal.arc_transaction_hash,
            },
        )
    return withdrawal


def reconcile_pending_withdrawals(limit: int = 25) -> int:
    reconciled = 0
    records = AgentWithdrawal.objects.select_related("owner_user", "worker").filter(
        status__in=PENDING_WITHDRAWAL_STATES,
        circle_transaction_id__isnull=False,
    ).exclude(circle_transaction_id="").order_by("created_at")[:limit]
    for withdrawal in records:
        before = withdrawal.status
        refreshed = reconcile_withdrawal(withdrawal)
        if before != refreshed.status:
            reconciled += 1
    return reconciled


def _lifetime_earned(worker: WorkerAgent) -> Decimal:
    try:
        atomic = Decimal(str(worker.reputation_snapshot.total_earned_atomic or 0))
    except Exception:
        atomic = Decimal("0")
    scale = Decimal(10) ** int(settings.ARC_USDC_DECIMALS)
    return _quantize(atomic / scale)


def _completed_withdrawn(worker: WorkerAgent) -> Decimal:
    value = worker.withdrawals.filter(status=AgentWithdrawal.Status.COMPLETED).aggregate(
        total=Sum("amount_usdc")
    )["total"]
    return _quantize(Decimal(str(value or "0")))


def owner_wallet_address(owner) -> str:
    wallet = WalletAccount.objects.filter(
        user=owner,
        blockchain=settings.ARC_BLOCKCHAIN,
    ).order_by("created_at").first()
    return str(wallet.address or "") if wallet else ""


def withdrawal_public(withdrawal: AgentWithdrawal | None) -> dict[str, Any] | None:
    if withdrawal is None:
        return None
    return {
        "id": str(withdrawal.id),
        "amount_usdc": str(_quantize(withdrawal.amount_usdc)),
        "destination_address": withdrawal.destination_address,
        "status": withdrawal.status,
        "circle_transaction_id": withdrawal.circle_transaction_id or "",
        "arc_transaction_hash": withdrawal.arc_transaction_hash,
        "failure_message": withdrawal.failure_message,
        "created_at": withdrawal.created_at.isoformat() if withdrawal.created_at else None,
        "completed_at": withdrawal.completed_at.isoformat() if withdrawal.completed_at else None,
    }


def wallet_snapshot(worker: WorkerAgent, owner, *, reconcile=True) -> dict[str, Any]:
    latest = worker.withdrawals.order_by("-created_at").first()
    if reconcile and latest and latest.status in PENDING_WITHDRAWAL_STATES and latest.circle_transaction_id:
        latest = reconcile_withdrawal(latest)
    if worker.owner_user_id != owner.id:
        raise AgentWithdrawalError("You do not own this agent.")
    balance = read_worker_usdc_balance(worker)
    lifetime = _lifetime_earned(worker)
    withdrawn = _completed_withdrawn(worker)
    earnings_remaining = _quantize(lifetime - withdrawn)
    operational_available = _quantize(balance - RESERVE_USDC)
    withdrawable = _quantize(min(earnings_remaining, operational_available))
    return {
        "agent_id": str(worker.id),
        "agent_name": worker.name,
        "wallet_address": worker.worker_wallet_address,
        "blockchain": worker.wallet_blockchain,
        "symbol": "USDC",
        "live_balance_usdc": str(balance),
        "lifetime_earned_usdc": str(lifetime),
        "withdrawn_usdc": str(withdrawn),
        "operational_reserve_usdc": str(RESERVE_USDC),
        "available_to_withdraw_usdc": str(withdrawable),
        "owner_wallet_address": owner_wallet_address(owner),
        "withdrawal_in_progress": bool(latest and latest.status in PENDING_WITHDRAWAL_STATES),
        "latest_withdrawal": withdrawal_public(latest),
    }


def create_withdrawal(*, worker: WorkerAgent, owner, destination_address: str, amount_usdc: Any) -> AgentWithdrawal:
    destination = str(destination_address or "").strip().lower()
    if not EVM_ADDRESS_RE.fullmatch(destination):
        raise AgentWithdrawalError("Enter a valid Arc/EVM destination wallet address.")
    if destination == str(worker.worker_wallet_address or "").lower():
        raise AgentWithdrawalError("Choose a destination different from the agent wallet.")
    amount = _quantize(_decimal(amount_usdc))
    if amount <= 0:
        raise AgentWithdrawalError("Withdrawal amount must be greater than zero.")

    with transaction.atomic():
        locked_worker = WorkerAgent.objects.select_for_update().get(pk=worker.pk)
        if locked_worker.owner_user_id != owner.id:
            raise AgentWithdrawalError("You do not own this agent.")
        existing = locked_worker.withdrawals.select_for_update().filter(
            status__in=PENDING_WITHDRAWAL_STATES
        ).order_by("-created_at").first()
        if existing:
            return existing
        if locked_worker.job_assignments.filter(
            status__in=ACTIVE_ASSIGNMENT_STATUSES
        ).exists():
            raise AgentWithdrawalError(
                "Wait for the agent to finish its current coding assignment before withdrawing."
            )

        snapshot = wallet_snapshot(locked_worker, owner, reconcile=False)
        available = _decimal(snapshot["available_to_withdraw_usdc"])
        if amount > available:
            raise AgentWithdrawalError(
                f"Only {available:.6f} USDC is currently available to withdraw."
            )

        withdrawal = AgentWithdrawal.objects.create(
            worker=locked_worker,
            owner_user=owner,
            destination_address=destination,
            amount_usdc=amount,
            status=AgentWithdrawal.Status.SUBMITTING,
        )

        developer_controlled_wallets, client = _init_circle()
        try:
            transactions_api = developer_controlled_wallets.TransactionsApi(client)
            request = developer_controlled_wallets.CreateTransferTransactionForDeveloperRequest.from_dict(
                {
                    "walletAddress": locked_worker.worker_wallet_address,
                    "blockchain": locked_worker.wallet_blockchain,
                    "destinationAddress": destination,
                    "tokenAddress": settings.ARC_USDC_ADDRESS,
                    "amounts": [str(amount)],
                    "feeLevel": "MEDIUM",
                }
            )
            response = transactions_api.create_developer_transaction_transfer(request)
            transaction_id, circle_state = _extract_transfer(response)
        except Exception as exc:
            withdrawal.status = AgentWithdrawal.Status.FAILED
            withdrawal.failure_message = f"Circle could not submit the withdrawal: {exc}"
            withdrawal.save(update_fields=["status", "failure_message", "updated_at"])
            raise AgentWithdrawalError(withdrawal.failure_message) from exc

        withdrawal.circle_transaction_id = transaction_id
        withdrawal.status = _circle_state_to_status(circle_state)
        withdrawal.submitted_at = timezone.now()
        if withdrawal.status == AgentWithdrawal.Status.COMPLETED:
            withdrawal.completed_at = timezone.now()
        withdrawal.save(
            update_fields=[
                "circle_transaction_id", "status", "submitted_at", "completed_at", "updated_at"
            ]
        )
        AuditLog.objects.create(
            actor=owner,
            action="AGENT_USDC_WITHDRAWAL_SUBMITTED",
            resource_type="WorkerAgent",
            resource_id=str(locked_worker.id),
            metadata={
                "withdrawal_id": str(withdrawal.id),
                "amount_usdc": str(amount),
                "destination_address": destination,
                "circle_transaction_id": transaction_id,
            },
        )
        return withdrawal
