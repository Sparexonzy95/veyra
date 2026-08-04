import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from web3 import Web3
from blockchain.client import ArcClient
from blockchain.services import available_client_action
from common.models import AuditLog
from common.utils import canonical_json, to_atomic_usdc
from jobs.models import JobDraft, JobFundingSnapshot, VeyraJob
from wallets.circle import CircleClient
from wallets.models import CircleTransaction, WalletAccount
from wallets.services import ensure_wallet_owned_by_circle_session

ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'



def _circle_response_value(response, *keys):
    if not isinstance(response, dict):
        return None
    for key in keys:
        value = response.get(key)
        if value not in (None, ''):
            return value
    nested = response.get('transaction')
    if isinstance(nested, dict):
        for key in keys:
            value = nested.get(key)
            if value not in (None, ''):
                return value
    return None

def commitment_hash(value) -> str:
    return Web3.to_hex(Web3.keccak(text=canonical_json(value)))

@transaction.atomic
def lock_funding_snapshot(draft: JobDraft):
    if draft.status == JobDraft.Status.FUNDED:
        raise ValidationError('Job is already funded.')
    if hasattr(draft, 'funding_snapshot'):
        return draft.funding_snapshot
    advanced = draft.advanced_options or {}
    verification_methods = advanced.get('criterion_verification_methods', [])
    structured_criteria = [
        {
            'statement': statement,
            'verificationMethod': (
                verification_methods[index]
                if index < len(verification_methods)
                else 'AUTOMATED_TEST'
            ),
        }
        for index, statement in enumerate(draft.acceptance_criteria)
    ]
    repository = {
        'version': 2,
        'host': 'github.com',
        'owner': draft.repository_owner,
        'repository': draft.repository_name,
        'targetBranch': draft.target_branch,
        'issueNumber': draft.issue_number,
        'githubRepositoryId': (
            int(draft.github_repository_access.github_repository_id)
            if draft.github_repository_access_id
            else 0
        ),
        'repositoryVisibility': (
            'PRIVATE'
            if draft.github_repository_access_id and draft.github_repository_access.private
            else 'PUBLIC'
        ),
        'repositoryStack': advanced.get('repository_stack', []),
    }
    task = {
        'version': 2,
        'title': advanced.get('job_title') or draft.issue_title,
        'workType': advanced.get('job_type', 'FEATURE'),
        'description': advanced.get('job_description') or draft.issue_body,
        'technicalRequirements': advanced.get('technical_requirements', []),
        'acceptanceCriteria': structured_criteria,
    }
    policy = {
        'version': 2,
        'requiredCommands': advanced.get('required_commands', []),
        'allowedPaths': advanced.get('allowed_paths', []),
        'forbiddenPaths': advanced.get('forbidden_paths', []),
        'deliveryType': advanced.get('delivery_type', 'PULL_REQUEST'),
        'agentAccess': 'INVITED' if advanced.get('invited_provider_address') else 'OPEN',
    }
    invited = (advanced.get('invited_provider_address') or ZERO_ADDRESS).lower()
    snapshot = JobFundingSnapshot.objects.create(
        draft=draft,
        repository_commitment=repository,
        task_commitment=task,
        policy_commitment=policy,
        repository_hash=commitment_hash(repository),
        task_hash=commitment_hash(task),
        policy_hash=commitment_hash(policy),
        budget_atomic=to_atomic_usdc(draft.budget_usdc),
        expires_at=int(draft.deadline.timestamp()),
        verifier_address=settings.VEYRA_VERIFIER_ADDRESS.lower(),
        invited_provider_address=invited,
    )
    draft.status = JobDraft.Status.LOCKED
    draft.save(update_fields=['status', 'updated_at'])
    return snapshot


def verify_circle_session_for_user(user, user_token):
    wallet = user.wallet_accounts.filter(
        blockchain=settings.ARC_BLOCKCHAIN,
        purpose=WalletAccount.Purpose.CLIENT_ESCROW,
    ).first()
    if not wallet:
        raise ValidationError('Arc wallet is not ready.')
    circle = CircleClient()
    ensure_wallet_owned_by_circle_session(circle.list_wallets(user_token), wallet)
    return circle, wallet


def _existing_active_transaction(user, wallet, purpose, draft):
    return CircleTransaction.objects.filter(
        user=user,
        wallet=wallet,
        draft=draft,
        purpose=purpose,
        status__in=[
            CircleTransaction.Status.CHALLENGE_READY,
            CircleTransaction.Status.USER_APPROVAL_PENDING,
            CircleTransaction.Status.SUBMITTED,
            CircleTransaction.Status.PENDING_ONCHAIN,
        ],
    ).order_by('-created_at').first()


def _create_contract_challenge(*, user, wallet, user_token, draft, purpose, contract_address, call_data, metadata, memo):
    existing = _existing_active_transaction(user, wallet, purpose, draft)
    if existing:
        # User-controlled contract execution challenges are created before a
        # Circle transaction ID exists. Reuse the stored challenge/transaction
        # record so refreshes and retries remain idempotent.
        return existing, True

    metadata = {
        **metadata,
        'memo': memo,
    }
    transaction_record = CircleTransaction.objects.create(
        user=user,
        wallet=wallet,
        draft=draft,
        purpose=purpose,
        status=CircleTransaction.Status.CREATED,
        contract_address=contract_address.lower(),
        call_data_hash=Web3.to_hex(Web3.keccak(hexstr=call_data)),
        request_metadata=metadata,
    )

    payload = {
        'idempotencyKey': str(transaction_record.idempotency_key),
        'walletId': wallet.circle_wallet_id,
        'contractAddress': contract_address,
        'callData': call_data,
        'feeLevel': 'MEDIUM',
        'memo': memo,
        # Circle returns this reference on the eventual transaction. It lets
        # Django find the transaction after the user completes the challenge.
        'refId': str(transaction_record.id),
    }

    response = CircleClient().create_contract_execution(user_token, payload)
    challenge_id = str(_circle_response_value(response, 'challengeId') or '').strip()
    circle_transaction_id = str(
        _circle_response_value(response, 'id', 'transactionId') or ''
    ).strip()
    circle_reference_id = str(
        _circle_response_value(response, 'refId', 'referenceId')
        or transaction_record.id
    ).strip()

    if not challenge_id:
        transaction_record.status = CircleTransaction.Status.FAILED
        transaction_record.failure_code = 'INVALID_CIRCLE_CREATE_RESPONSE'
        transaction_record.failure_message = 'Circle did not return a challenge ID.'
        transaction_record.save(update_fields=[
            'status', 'failure_code', 'failure_message', 'updated_at',
        ])
        raise ValidationError('Circle did not return a transaction challenge.')

    if circle_transaction_id:
        conflict = CircleTransaction.objects.filter(
            circle_transaction_id=circle_transaction_id,
        ).exclude(id=transaction_record.id).exists()
        if conflict:
            transaction_record.status = CircleTransaction.Status.FAILED
            transaction_record.failure_code = 'CIRCLE_TRANSACTION_ID_CONFLICT'
            transaction_record.failure_message = (
                'Circle returned a transaction ID already linked to another action.'
            )
            transaction_record.save(update_fields=[
                'status', 'failure_code', 'failure_message', 'updated_at',
            ])
            raise ValidationError('Circle returned a duplicate transaction ID.')

    transaction_record.circle_challenge_id = challenge_id
    transaction_record.circle_transaction_id = circle_transaction_id or None
    transaction_record.circle_reference_id = circle_reference_id
    transaction_record.status = CircleTransaction.Status.CHALLENGE_READY
    transaction_record.save(update_fields=[
        'circle_challenge_id', 'circle_transaction_id',
        'circle_reference_id', 'status', 'updated_at',
    ])
    return transaction_record, False


def create_approval_challenge(draft, user_token):
    snapshot = lock_funding_snapshot(draft)
    circle, wallet = verify_circle_session_for_user(draft.client, user_token)
    arc = ArcClient()
    allowance = arc.allowance(wallet.address)
    required = int(snapshot.budget_atomic)
    if allowance >= required:
        return {'approval_required': False, 'allowance_atomic': allowance}
    call_data = arc.encode_approve(required)
    tx, reused = _create_contract_challenge(
        user=draft.client,
        wallet=wallet,
        user_token=user_token,
        draft=draft,
        purpose=CircleTransaction.Purpose.USDC_APPROVAL,
        contract_address=settings.ARC_USDC_ADDRESS,
        call_data=call_data,
        metadata={'draft_id': str(draft.id), 'amount_atomic': required},
        memo=f'Approve USDC for Veyra job {draft.id}',
    )
    requires_user_approval = tx.status in {
        CircleTransaction.Status.CREATED,
        CircleTransaction.Status.CHALLENGE_READY,
    }
    return {
        'approval_required': True,
        'challenge_id': tx.circle_challenge_id if requires_user_approval else None,
        'transaction_id': tx.id,
        'transaction_status': tx.status,
        'requires_user_approval': requires_user_approval,
        'reused': reused,
    }


def create_job_challenge(draft, user_token):
    snapshot = lock_funding_snapshot(draft)
    _, wallet = verify_circle_session_for_user(draft.client, user_token)
    arc = ArcClient()
    if arc.is_paused():
        raise ValidationError('Veyra escrow is currently paused.')
    if not arc.is_verifier_authorised(snapshot.verifier_address):
        raise ValidationError('Configured verifier is not authorised onchain.')
    if snapshot.invited_provider_address != ZERO_ADDRESS and not arc.is_agent_authorised(snapshot.invited_provider_address):
        raise ValidationError('Invited agent is not authorised onchain.')
    required = int(snapshot.budget_atomic)
    if arc.allowance(wallet.address) < required:
        raise ValidationError('USDC approval has not been confirmed on Arc yet.')
    call_data = arc.encode_create_job(
        invited_provider=snapshot.invited_provider_address,
        verifier=snapshot.verifier_address,
        budget_atomic=required,
        expires_at=snapshot.expires_at,
        repository_hash=snapshot.repository_hash,
        task_hash=snapshot.task_hash,
        policy_hash=snapshot.policy_hash,
    )
    tx, reused = _create_contract_challenge(
        user=draft.client,
        wallet=wallet,
        user_token=user_token,
        draft=draft,
        purpose=CircleTransaction.Purpose.JOB_CREATE,
        contract_address=settings.VEYRA_CONTRACT_ADDRESS,
        call_data=call_data,
        metadata={'draft_id': str(draft.id), 'snapshot_id': str(snapshot.id)},
        memo=f'Fund Veyra job {draft.id}',
    )
    draft.status = JobDraft.Status.FUNDING
    draft.save(update_fields=['status', 'updated_at'])
    requires_user_approval = tx.status in {
        CircleTransaction.Status.CREATED,
        CircleTransaction.Status.CHALLENGE_READY,
    }
    return {
        'challenge_id': tx.circle_challenge_id if requires_user_approval else None,
        'transaction_id': tx.id,
        'transaction_status': tx.status,
        'requires_user_approval': requires_user_approval,
        'reused': reused,
    }


def refresh_job_projection(job: VeyraJob):
    onchain = ArcClient().get_job(job.onchain_job_id)
    job.status = onchain['status']
    action = available_client_action(onchain)
    job.client_status = 'REFUND_AVAILABLE' if action and action['code'] == 'CLAIM_REFUND' else onchain['client_status']
    job.provider_address = onchain['provider'] if onchain['provider'] != ZERO_ADDRESS else ''
    job.claim_deadline = onchain['claim_deadline']
    job.deliverable_hash = onchain['deliverable_hash']
    job.commit_hash = onchain['commit_hash']
    job.pull_request_number = onchain['pull_request_number']
    job.report_hash = onchain['report_hash']
    job.evidence_hash = onchain['evidence_hash']
    job.rejection_reason_hash = onchain['rejection_reason_hash']
    job.save()
    return onchain


def create_contextual_action_challenge(job, user_token):
    _, wallet = verify_circle_session_for_user(job.client, user_token)
    onchain = ArcClient().get_job(job.onchain_job_id)
    if onchain['client'] != wallet.address.lower():
        raise AuthenticationFailed('This wallet is not the onchain client for the job.')
    action = available_client_action(onchain)
    if not action:
        raise ValidationError('No client action is currently available for this job.')
    call_data = ArcClient().encode_client_action(action['contract_function'], job.onchain_job_id)
    purpose = CircleTransaction.Purpose.JOB_CANCEL if action['code'] == 'CANCEL_JOB' else CircleTransaction.Purpose.JOB_REFUND
    tx, reused = _create_contract_challenge(
        user=job.client,
        wallet=wallet,
        user_token=user_token,
        draft=job.draft,
        purpose=purpose,
        contract_address=settings.VEYRA_CONTRACT_ADDRESS,
        call_data=call_data,
        metadata={
            'draft_id': str(job.draft_id),
            'job_id': job.onchain_job_id,
            'action': action['code'],
            'contract_function': action['contract_function'],
            'expected_event': {
                'cancelUnclaimedJob': 'JobCancelled',
                'refundAbandonedClaim': 'ClaimAbandoned',
                'claimExpiredRefund': 'JobExpired',
            }[action['contract_function']],
        },
        memo=f"{action['label']} for Veyra job {job.onchain_job_id}",
    )
    requires_user_approval = tx.status in {
        CircleTransaction.Status.CREATED,
        CircleTransaction.Status.CHALLENGE_READY,
    }
    return {
        'action': action,
        'challenge_id': tx.circle_challenge_id if requires_user_approval else None,
        'transaction_id': tx.id,
        'transaction_status': tx.status,
        'requires_user_approval': requires_user_approval,
        'reused': reused,
    }
