from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from web3 import Web3

from blockchain.client import ArcClient
from blockchain.services import bytes_json
from jobs.models import JobDraft, JobFundingSnapshot, Notification, VeyraJob
from wallets.circle import CircleClient, CircleError
from wallets.models import CircleTransaction

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {
    CircleTransaction.Status.CONFIRMED,
    CircleTransaction.Status.DENIED,
    CircleTransaction.Status.FAILED,
    CircleTransaction.Status.EXPIRED,
    CircleTransaction.Status.EVENT_MISMATCH,
}

CIRCLE_STATE_MAP = {
    'INITIATED': CircleTransaction.Status.SUBMITTED,
    'PENDING': CircleTransaction.Status.SUBMITTED,
    'QUEUED': CircleTransaction.Status.SUBMITTED,
    'SENT': CircleTransaction.Status.SUBMITTED,
    'COMPLETE': CircleTransaction.Status.PENDING_ONCHAIN,
    'CONFIRMED': CircleTransaction.Status.PENDING_ONCHAIN,
    'FAILED': CircleTransaction.Status.FAILED,
    'DENIED': CircleTransaction.Status.DENIED,
    'CANCELLED': CircleTransaction.Status.FAILED,
    'CANCELED': CircleTransaction.Status.FAILED,
    'EXPIRED': CircleTransaction.Status.EXPIRED,
}


def _remote_value(remote: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = remote.get(key)
        if value not in (None, ''):
            return value
    return None


def _hex(value: Any) -> str:
    if value in (None, ''):
        return ''
    if isinstance(value, str):
        return value.lower()
    return Web3.to_hex(value).lower()


def _address(value: Any) -> str:
    return str(value or '').lower()



def _remote_transaction_object(remote: dict[str, Any]) -> dict[str, Any]:
    """Normalize Circle list/get response wrappers into one transaction object."""
    transaction = remote.get('transaction')
    if isinstance(transaction, dict):
        return transaction

    data = remote.get('data')
    if isinstance(data, dict):
        nested = data.get('transaction')
        if isinstance(nested, dict):
            return nested
        return data

    return remote


def _remote_datetime(remote: dict[str, Any]):
    raw = _remote_value(
        remote,
        'createDate',
        'createdAt',
        'create_date',
        'updateDate',
        'updatedAt',
    )
    if not raw:
        return None
    value = parse_datetime(str(raw))
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _expected_memo(tx: CircleTransaction) -> str:
    explicit = str(tx.request_metadata.get('memo') or '').strip()
    if explicit:
        return explicit
    if not tx.draft_id:
        return ''
    if tx.purpose == CircleTransaction.Purpose.USDC_APPROVAL:
        return f'Approve USDC for Veyra job {tx.draft_id}'
    if tx.purpose == CircleTransaction.Purpose.JOB_CREATE:
        return f'Fund Veyra job {tx.draft_id}'
    return ''


def _candidate_score(tx: CircleTransaction, remote: dict[str, Any]) -> tuple[int, float]:
    """
    Score a Circle transaction candidate without trusting it as final proof.

    The chosen Circle record is still validated against the exact Arc sender,
    target contract and calldata hash before any Veyra state can be confirmed.
    """
    remote = _remote_transaction_object(remote)

    remote_id = str(_remote_value(remote, 'id', 'transactionId') or '').strip()
    if not remote_id:
        return (-1, float('inf'))

    if CircleTransaction.objects.filter(
        circle_transaction_id=remote_id,
    ).exclude(id=tx.id).exists():
        return (-1, float('inf'))

    score = 0

    reference_id = str(_remote_value(remote, 'refId', 'referenceId') or '').strip()
    if reference_id:
        if reference_id not in {str(tx.id), str(tx.circle_reference_id or '')}:
            return (-1, float('inf'))
        score += 100

    challenge_id = str(_remote_value(remote, 'challengeId') or '').strip()
    if challenge_id:
        if challenge_id != str(tx.circle_challenge_id or ''):
            return (-1, float('inf'))
        score += 90

    idempotency_key = str(
        _remote_value(remote, 'idempotencyKey', 'idempotency_key') or ''
    ).strip()
    if idempotency_key:
        if idempotency_key != str(tx.idempotency_key):
            return (-1, float('inf'))
        score += 80

    wallet_id = str(_remote_value(remote, 'walletId') or '').strip()
    if wallet_id:
        if wallet_id != tx.wallet.circle_wallet_id:
            return (-1, float('inf'))
        score += 25

    source_address = _address(
        _remote_value(remote, 'sourceAddress', 'fromAddress', 'from')
    )
    if source_address:
        if source_address != tx.wallet.address.lower():
            return (-1, float('inf'))
        score += 20

    blockchain = str(_remote_value(remote, 'blockchain') or '').strip()
    if blockchain:
        if blockchain != settings.ARC_BLOCKCHAIN:
            return (-1, float('inf'))
        score += 10

    contract_address = _address(
        _remote_value(remote, 'contractAddress', 'destinationAddress', 'to')
    )
    if contract_address:
        if contract_address != tx.contract_address.lower():
            return (-1, float('inf'))
        score += 35

    operation = str(_remote_value(remote, 'operation') or '').upper()
    if operation:
        if operation != 'CONTRACT_EXECUTION':
            return (-1, float('inf'))
        score += 10

    memo = str(_remote_value(remote, 'memo') or '').strip()
    expected_memo = _expected_memo(tx)
    if memo and expected_memo:
        if memo != expected_memo:
            return (-1, float('inf'))
        score += 60

    remote_time = _remote_datetime(remote)
    anchor = tx.submitted_at or tx.created_at
    distance = float('inf')
    if remote_time and anchor:
        distance = abs((remote_time - anchor).total_seconds())
        if distance > 30 * 60:
            return (-1, distance)
        score += max(0, 30 - int(distance // 10))

    return (score, distance)


def _choose_remote_transaction(
    tx: CircleTransaction,
    remote_transactions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized = [
        _remote_transaction_object(item)
        for item in remote_transactions
        if isinstance(item, dict)
    ]

    exact: list[dict[str, Any]] = []
    expected_references = {str(tx.id), str(tx.circle_reference_id or '')}
    for remote in normalized:
        reference_id = str(
            _remote_value(remote, 'refId', 'referenceId') or ''
        ).strip()
        challenge_id = str(_remote_value(remote, 'challengeId') or '').strip()
        idempotency_key = str(
            _remote_value(remote, 'idempotencyKey', 'idempotency_key') or ''
        ).strip()

        if (
            reference_id and reference_id in expected_references
        ) or (
            challenge_id
            and challenge_id == str(tx.circle_challenge_id or '')
        ) or (
            idempotency_key
            and idempotency_key == str(tx.idempotency_key)
        ):
            exact.append(remote)

    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    scored: list[tuple[int, float, dict[str, Any]]] = []
    for remote in normalized:
        score, distance = _candidate_score(tx, remote)
        if score >= 45:
            scored.append((score, distance, remote))

    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], item[1]))
    best = scored[0]
    if len(scored) == 1:
        return best[2]

    second = scored[1]
    if best[0] - second[0] >= 15:
        return best[2]
    if best[1] + 15 < second[1]:
        return best[2]
    return None


def _mark_failure(tx: CircleTransaction, *, code: str, message: str, status: str) -> CircleTransaction:
    tx.status = status
    tx.failure_code = code
    tx.failure_message = message
    tx.last_checked_at = timezone.now()
    tx.sync_attempts += 1
    tx.save(update_fields=[
        'status', 'failure_code', 'failure_message', 'last_checked_at',
        'sync_attempts', 'updated_at',
    ])
    if (
        status in {
            CircleTransaction.Status.FAILED,
            CircleTransaction.Status.DENIED,
            CircleTransaction.Status.EXPIRED,
        }
        and tx.purpose == CircleTransaction.Purpose.JOB_CREATE
        and tx.draft_id
    ):
        JobDraft.objects.filter(
            id=tx.draft_id,
            status=JobDraft.Status.FUNDING,
        ).update(status=JobDraft.Status.LOCKED, updated_at=timezone.now())
    return tx


def _validate_remote_transaction(tx: CircleTransaction, remote: dict[str, Any]) -> None:
    remote = _remote_transaction_object(remote)

    remote_id = _remote_value(remote, 'id', 'transactionId')
    if remote_id and tx.circle_transaction_id and str(remote_id) != tx.circle_transaction_id:
        raise ValidationError('Circle returned a different transaction ID.')

    wallet_id = _remote_value(remote, 'walletId')
    if wallet_id and wallet_id != tx.wallet.circle_wallet_id:
        raise ValidationError('Circle transaction belongs to a different wallet.')

    source_address = _remote_value(remote, 'sourceAddress', 'fromAddress', 'from')
    if source_address and _address(source_address) != tx.wallet.address.lower():
        raise ValidationError('Circle transaction source does not match the client wallet.')

    blockchain = _remote_value(remote, 'blockchain')
    if blockchain and blockchain != settings.ARC_BLOCKCHAIN:
        raise ValidationError('Circle transaction is on the wrong blockchain.')

    contract_address = _remote_value(remote, 'contractAddress', 'destinationAddress', 'to')
    if contract_address and _address(contract_address) != _address(tx.contract_address):
        raise ValidationError('Circle transaction targets a different contract.')

    remote_call_data = _remote_value(remote, 'callData', 'calldata')
    if remote_call_data and tx.call_data_hash:
        remote_input = _hex(remote_call_data)
        remote_hash = Web3.to_hex(Web3.keccak(hexstr=remote_input)).lower()
        if remote_hash != tx.call_data_hash.lower():
            raise ValidationError('Circle transaction call data does not match this Veyra action.')

    reference_id = _remote_value(remote, 'refId', 'referenceId')
    if reference_id and str(reference_id) not in {str(tx.id), str(tx.circle_reference_id or '')}:
        raise ValidationError('Circle transaction reference does not match this Veyra action.')



def mark_challenge_completed(tx: CircleTransaction) -> CircleTransaction:
    """Record that the user approved the Circle challenge in the Web SDK."""
    if tx.status in TERMINAL_STATUSES:
        return tx
    if tx.status in {
        CircleTransaction.Status.CREATED,
        CircleTransaction.Status.CHALLENGE_READY,
        CircleTransaction.Status.USER_APPROVAL_PENDING,
    }:
        tx.status = CircleTransaction.Status.USER_APPROVAL_PENDING
        tx.submitted_at = tx.submitted_at or timezone.now()
        tx.failure_code = ''
        tx.failure_message = ''
        tx.save(update_fields=[
            'status', 'submitted_at', 'failure_code', 'failure_message',
            'updated_at',
        ])
    return tx


def resolve_circle_transaction_id(
    tx: CircleTransaction,
    user_token: str,
) -> CircleTransaction:
    """
    Resolve the Circle transaction created after a user-controlled challenge.

    Circle may omit refId from list results in some environments. Veyra first
    uses refId/challenge/idempotency identifiers, then safely falls back to the
    authenticated wallet, exact contract, blockchain, operation, memo and
    creation time. Arc sender/target/calldata validation remains mandatory.
    """
    if tx.circle_transaction_id:
        return tx

    try:
        remote_transactions = CircleClient().list_transactions(
            user_token,
            wallet_id=tx.wallet.circle_wallet_id,
        )
    except CircleError as exc:
        if exc.status_code in {404, 409, 429, 500, 502, 503, 504}:
            logger.info('Circle transaction list not ready for %s: %s', tx.id, exc)
            return tx
        raise

    remote = _choose_remote_transaction(tx, remote_transactions)
    if not remote:
        logger.info(
            'Circle transaction unresolved for %s: remote_count=%s purpose=%s contract=%s',
            tx.id,
            len(remote_transactions),
            tx.purpose,
            tx.contract_address,
        )
        return tx

    _validate_remote_transaction(tx, remote)
    remote_id = str(_remote_value(remote, 'id', 'transactionId') or '').strip()
    if not remote_id:
        return tx

    conflict = CircleTransaction.objects.filter(
        circle_transaction_id=remote_id,
    ).exclude(id=tx.id).exists()
    if conflict:
        return _mark_failure(
            tx,
            code='CIRCLE_TRANSACTION_ID_CONFLICT',
            message='Circle transaction is already linked to another Veyra action.',
            status=CircleTransaction.Status.EVENT_MISMATCH,
        )

    remote_reference = str(
        _remote_value(remote, 'refId', 'referenceId') or ''
    ).strip()

    tx.circle_transaction_id = remote_id
    tx.circle_reference_id = remote_reference or str(tx.id)
    if tx.status in {
        CircleTransaction.Status.CREATED,
        CircleTransaction.Status.CHALLENGE_READY,
        CircleTransaction.Status.USER_APPROVAL_PENDING,
    }:
        tx.status = CircleTransaction.Status.SUBMITTED
    tx.submitted_at = tx.submitted_at or timezone.now()
    tx.save(update_fields=[
        'circle_transaction_id', 'circle_reference_id', 'status',
        'submitted_at', 'updated_at',
    ])
    return tx

def refresh_circle_transaction(tx: CircleTransaction, user_token: str) -> CircleTransaction:
    if not tx.circle_transaction_id:
        return tx

    try:
        remote = CircleClient().get_transaction(user_token, tx.circle_transaction_id)
    except CircleError as exc:
        # Circle may be eventually consistent immediately after the SDK callback.
        if exc.status_code in {404, 409, 429, 500, 502, 503, 504}:
            logger.info('Circle transaction %s not ready: %s', tx.id, exc)
            return tx
        raise

    if not isinstance(remote, dict):
        return tx

    _validate_remote_transaction(tx, remote)
    tx_hash = _remote_value(remote, 'txHash', 'transactionHash')
    state = str(_remote_value(remote, 'state', 'status') or '').upper()
    mapped = CIRCLE_STATE_MAP.get(state)

    update_fields = ['updated_at']
    if tx_hash:
        normalized_hash = str(tx_hash).lower()
        if tx.arc_transaction_hash and tx.arc_transaction_hash.lower() != normalized_hash:
            raise ValidationError('Circle transaction hash changed unexpectedly.')
        tx.arc_transaction_hash = normalized_hash
        update_fields.append('arc_transaction_hash')

    reference_id = _remote_value(remote, 'refId', 'referenceId')
    if reference_id:
        tx.circle_reference_id = str(reference_id)
        update_fields.append('circle_reference_id')

    if mapped:
        tx.status = mapped
        update_fields.append('status')
        if mapped in {CircleTransaction.Status.SUBMITTED, CircleTransaction.Status.PENDING_ONCHAIN} and not tx.submitted_at:
            tx.submitted_at = timezone.now()
            update_fields.append('submitted_at')
        if mapped in TERMINAL_STATUSES:
            tx.failure_code = state
            tx.failure_message = str(_remote_value(remote, 'errorReason', 'errorMessage') or state.title())
            update_fields.extend(['failure_code', 'failure_message'])

    tx.save(update_fields=list(dict.fromkeys(update_fields)))
    if (
        mapped in {
            CircleTransaction.Status.FAILED,
            CircleTransaction.Status.DENIED,
            CircleTransaction.Status.EXPIRED,
        }
        and tx.purpose == CircleTransaction.Purpose.JOB_CREATE
        and tx.draft_id
    ):
        JobDraft.objects.filter(
            id=tx.draft_id,
            status=JobDraft.Status.FUNDING,
        ).update(status=JobDraft.Status.LOCKED, updated_at=timezone.now())
    return tx


def attach_circle_transaction(
    tx: CircleTransaction,
    *,
    circle_transaction_id: str,
    user_token: str,
) -> CircleTransaction:
    circle_transaction_id = circle_transaction_id.strip()
    if not circle_transaction_id:
        raise ValidationError('circle_transaction_id is required.')
    if tx.circle_transaction_id and tx.circle_transaction_id != circle_transaction_id:
        raise ValidationError('A different Circle transaction is already linked to this action.')
    conflict = CircleTransaction.objects.filter(circle_transaction_id=circle_transaction_id).exclude(id=tx.id).first()
    if conflict:
        raise ValidationError('Circle transaction is already linked to another Veyra action.')

    tx.circle_transaction_id = circle_transaction_id
    tx.status = CircleTransaction.Status.SUBMITTED
    tx.submitted_at = tx.submitted_at or timezone.now()
    tx.failure_code = ''
    tx.failure_message = ''
    tx.save(update_fields=[
        'circle_transaction_id', 'status', 'submitted_at', 'failure_code',
        'failure_message', 'updated_at',
    ])
    return refresh_circle_transaction(tx, user_token)


def _validate_arc_transaction(tx: CircleTransaction, arc_transaction: Any) -> tuple[bool, str]:
    sender = _address(arc_transaction.get('from'))
    target = _address(arc_transaction.get('to'))
    input_data = _hex(arc_transaction.get('input', '0x'))

    if sender != tx.wallet.address.lower():
        return False, 'Arc transaction sender does not match the client wallet.'
    if target != tx.contract_address.lower():
        return False, 'Arc transaction target does not match the prepared contract.'
    input_hash = Web3.to_hex(Web3.keccak(hexstr=input_data)).lower()
    if tx.call_data_hash and input_hash != tx.call_data_hash.lower():
        return False, 'Arc transaction call data does not match the prepared Veyra action.'
    return True, ''


def _event_mismatch(tx: CircleTransaction, message: str, payload: dict[str, Any] | None = None) -> CircleTransaction:
    if payload is not None:
        tx.event_payload = bytes_json(payload)
        tx.save(update_fields=['event_payload', 'updated_at'])
    return _mark_failure(
        tx,
        code='EVENT_MISMATCH',
        message=message,
        status=CircleTransaction.Status.EVENT_MISMATCH,
    )


def _confirm_approval(tx: CircleTransaction, arc: ArcClient) -> CircleTransaction:
    required = int(tx.request_metadata.get('amount_atomic') or 0)
    allowance = int(arc.allowance(tx.wallet.address))
    if allowance < required:
        return _event_mismatch(
            tx,
            f'Approval transaction confirmed, but allowance is {allowance}; expected at least {required}.',
            {'allowance_atomic': allowance, 'required_atomic': required},
        )
    tx.event_payload = {
        'owner': tx.wallet.address,
        'spender': settings.VEYRA_CONTRACT_ADDRESS.lower(),
        'allowance_atomic': allowance,
        'required_atomic': required,
    }
    return tx


def _job_created_expected(snapshot: JobFundingSnapshot, tx: CircleTransaction) -> dict[str, Any]:
    return {
        'client': tx.wallet.address.lower(),
        'verifier': snapshot.verifier_address.lower(),
        'invitedProvider': snapshot.invited_provider_address.lower(),
        'budget': int(snapshot.budget_atomic),
        'expiresAt': int(snapshot.expires_at),
        'repositoryHash': snapshot.repository_hash.lower(),
        'taskHash': snapshot.task_hash.lower(),
        'policyHash': snapshot.policy_hash.lower(),
    }


def _normalise_job_created(args: dict[str, Any]) -> dict[str, Any]:
    return {
        'jobId': int(args['jobId']),
        'client': _address(args['client']),
        'verifier': _address(args['verifier']),
        'invitedProvider': _address(args['invitedProvider']),
        'budget': int(args['budget']),
        'expiresAt': int(args['expiresAt']),
        'repositoryHash': _hex(args['repositoryHash']),
        'taskHash': _hex(args['taskHash']),
        'policyHash': _hex(args['policyHash']),
    }


def _confirm_job_created(tx: CircleTransaction, arc: ArcClient, receipt: Any) -> CircleTransaction:
    snapshot_id = tx.request_metadata.get('snapshot_id')
    if not snapshot_id:
        return _event_mismatch(tx, 'Funding transaction has no locked snapshot reference.')
    try:
        snapshot = JobFundingSnapshot.objects.select_related('draft').get(id=snapshot_id)
    except JobFundingSnapshot.DoesNotExist:
        return _event_mismatch(tx, 'Locked funding snapshot was not found.')

    logs = arc.decode_receipt_event('JobCreated', receipt)
    if len(logs) != 1:
        return _event_mismatch(tx, f'Expected one JobCreated event, found {len(logs)}.')

    actual = _normalise_job_created(dict(logs[0]['args']))
    expected = _job_created_expected(snapshot, tx)
    mismatches = [
        key for key, expected_value in expected.items()
        if actual.get(key) != expected_value
    ]
    if mismatches:
        return _event_mismatch(
            tx,
            f'JobCreated event did not match the locked job terms: {", ".join(mismatches)}.',
            actual,
        )

    with db_transaction.atomic():
        locked_tx = CircleTransaction.objects.select_for_update().get(id=tx.id)
        existing = VeyraJob.objects.filter(onchain_job_id=actual['jobId']).first()
        if existing and existing.draft_id != snapshot.draft_id:
            locked_tx.status = CircleTransaction.Status.EVENT_MISMATCH
            locked_tx.failure_code = 'JOB_ID_CONFLICT'
            locked_tx.failure_message = 'Onchain job ID is already linked to a different draft.'
            locked_tx.event_payload = actual
            locked_tx.save(update_fields=[
                'status', 'failure_code', 'failure_message', 'event_payload', 'updated_at',
            ])
            return locked_tx

        job, _ = VeyraJob.objects.update_or_create(
            onchain_job_id=actual['jobId'],
            defaults={
                'client': snapshot.draft.client,
                'draft': snapshot.draft,
                'status': 'FUNDED',
                'client_status': 'OPEN',
                'client_address': actual['client'],
                'invited_provider_address': actual['invitedProvider'],
                'provider_address': '',
                'verifier_address': actual['verifier'],
                'budget_atomic': actual['budget'],
                'expires_at': actual['expiresAt'],
                'repository_hash': actual['repositoryHash'],
                'task_hash': actual['taskHash'],
                'policy_hash': actual['policyHash'],
                'creation_tx_hash': locked_tx.arc_transaction_hash,
            },
        )
        snapshot.draft.status = JobDraft.Status.FUNDED
        snapshot.draft.save(update_fields=['status', 'updated_at'])
        locked_tx.job = job
        locked_tx.event_payload = actual
        locked_tx.save(update_fields=['job', 'event_payload', 'updated_at'])
        Notification.objects.get_or_create(
            user=snapshot.draft.client,
            event_type='JOB_CREATED',
            resource_type='VeyraJob',
            resource_id=str(actual['jobId']),
            defaults={
                'title': 'Job funded and open',
                'body': f'{snapshot.draft.budget_usdc} USDC is secured in Veyra escrow.',
            },
        )
        tx = locked_tx
    return tx


def _confirm_contextual_action(tx: CircleTransaction, arc: ArcClient, receipt: Any) -> CircleTransaction:
    expected_event = tx.request_metadata.get('expected_event')
    job_id = int(tx.request_metadata.get('job_id') or 0)
    if not expected_event or not job_id:
        return _event_mismatch(tx, 'Client action is missing its expected event metadata.')
    logs = arc.decode_receipt_event(expected_event, receipt)
    matching = [log for log in logs if int(log['args'].get('jobId', 0)) == job_id]
    if len(matching) != 1:
        return _event_mismatch(tx, f'Expected one {expected_event} event for job {job_id}.')

    payload = bytes_json(dict(matching[0]['args']))
    job = VeyraJob.objects.filter(onchain_job_id=job_id, client=tx.user).first()
    if not job:
        return _event_mismatch(tx, 'The confirmed action references an unknown client job.', payload)

    if expected_event == 'JobCancelled':
        job.status, job.client_status = 'CANCELLED', 'CANCELLED'
    elif expected_event == 'ClaimAbandoned':
        job.status, job.client_status = 'ABANDONED', 'REFUNDED'
    elif expected_event == 'JobExpired':
        job.status, job.client_status = 'EXPIRED', 'REFUNDED'
    else:
        return _event_mismatch(tx, f'Unsupported client action event: {expected_event}.', payload)
    job.save(update_fields=['status', 'client_status', 'updated_at'])
    tx.job = job
    tx.event_payload = payload
    return tx


def _confirm_receipt(tx: CircleTransaction, arc: ArcClient, receipt: Any) -> CircleTransaction:
    if tx.purpose == CircleTransaction.Purpose.USDC_APPROVAL:
        return _confirm_approval(tx, arc)
    if tx.purpose == CircleTransaction.Purpose.JOB_CREATE:
        return _confirm_job_created(tx, arc, receipt)
    if tx.purpose in {CircleTransaction.Purpose.JOB_CANCEL, CircleTransaction.Purpose.JOB_REFUND}:
        return _confirm_contextual_action(tx, arc, receipt)
    return _event_mismatch(tx, f'No receipt validator is configured for {tx.purpose}.')


def sync_transaction(
    tx: CircleTransaction,
    *,
    user_token: str | None = None,
    force: bool = False,
) -> CircleTransaction:
    if tx.status in TERMINAL_STATUSES:
        return tx

    now = timezone.now()
    minimum_interval = getattr(settings, 'ARC_TRANSACTION_SYNC_MIN_INTERVAL_SECONDS', 2)
    if (
        not force
        and tx.last_checked_at
        and now - tx.last_checked_at < timedelta(seconds=minimum_interval)
    ):
        return tx

    if user_token:
        if not tx.circle_transaction_id:
            tx = resolve_circle_transaction_id(tx, user_token)
            if tx.status in TERMINAL_STATUSES:
                return tx
        if tx.circle_transaction_id:
            tx = refresh_circle_transaction(tx, user_token)
            if tx.status in TERMINAL_STATUSES:
                return tx

    if not tx.arc_transaction_hash:
        tx.last_checked_at = now
        tx.sync_attempts += 1
        tx.save(update_fields=['last_checked_at', 'sync_attempts', 'updated_at'])
        return tx

    arc = ArcClient()
    try:
        receipt = arc.transaction_receipt_or_none(tx.arc_transaction_hash)
    except Exception as exc:
        logger.warning('Arc receipt check failed for %s: %s', tx.id, exc)
        tx.last_checked_at = now
        tx.sync_attempts += 1
        tx.save(update_fields=['last_checked_at', 'sync_attempts', 'updated_at'])
        return tx

    if receipt is None:
        tx.status = CircleTransaction.Status.PENDING_ONCHAIN
        tx.last_checked_at = now
        tx.sync_attempts += 1
        tx.save(update_fields=['status', 'last_checked_at', 'sync_attempts', 'updated_at'])
        return tx

    # Circle user-controlled SCA wallets use account abstraction. The outer Arc
    # transaction may be submitted by a bundler/EntryPoint and therefore its
    # `from`, `to`, and `input` fields are not the client's intended contract
    # call. For SCA wallets, identity and intent are verified from the
    # authenticated Circle transaction, then business correctness is proven by
    # the resulting on-chain allowance or Veyra contract event below.
    if tx.wallet.account_type.upper() != 'SCA':
        try:
            arc_transaction = arc.transaction(tx.arc_transaction_hash)
        except Exception as exc:
            logger.warning('Arc transaction lookup failed for %s: %s', tx.id, exc)
            tx.last_checked_at = now
            tx.sync_attempts += 1
            tx.save(update_fields=['last_checked_at', 'sync_attempts', 'updated_at'])
            return tx

        valid, mismatch = _validate_arc_transaction(tx, arc_transaction)
        if not valid:
            return _event_mismatch(tx, mismatch)

    tx.receipt_status = int(receipt.get('status', 0))
    tx.block_number = int(receipt.get('blockNumber', 0))
    tx.gas_used = int(receipt.get('gasUsed', 0))
    tx.last_checked_at = now
    tx.sync_attempts += 1
    tx.save(update_fields=[
        'receipt_status', 'block_number', 'gas_used', 'last_checked_at',
        'sync_attempts', 'updated_at',
    ])

    if tx.receipt_status != 1:
        return _mark_failure(
            tx,
            code='ARC_REVERTED',
            message='The Arc transaction reverted.',
            status=CircleTransaction.Status.FAILED,
        )

    tx = _confirm_receipt(tx, arc, receipt)
    if tx.status == CircleTransaction.Status.EVENT_MISMATCH:
        return tx

    tx.status = CircleTransaction.Status.CONFIRMED
    tx.confirmed_at = timezone.now()
    tx.failure_code = ''
    tx.failure_message = ''
    tx.save(update_fields=[
        'status', 'confirmed_at', 'failure_code', 'failure_message', 'job',
        'event_payload', 'updated_at',
    ])
    return tx


def transaction_payload(tx: CircleTransaction) -> dict[str, Any]:
    return {
        'id': str(tx.id),
        'purpose': tx.purpose,
        'status': tx.status,
        'challenge_id': tx.circle_challenge_id,
        'circle_transaction_id': tx.circle_transaction_id,
        'arc_transaction_hash': tx.arc_transaction_hash,
        'contract_address': tx.contract_address,
        'draft_id': str(tx.draft_id) if tx.draft_id else None,
        'job_id': tx.job.onchain_job_id if tx.job_id else None,
        'block_number': tx.block_number,
        'gas_used': tx.gas_used,
        'failure_code': tx.failure_code,
        'failure_message': tx.failure_message,
        'event_payload': tx.event_payload,
        'submitted_at': tx.submitted_at,
        'confirmed_at': tx.confirmed_at,
        'created_at': tx.created_at,
        'updated_at': tx.updated_at,
        'terminal': tx.status in TERMINAL_STATUSES,
    }