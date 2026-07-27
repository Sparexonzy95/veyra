import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from web3 import Web3
from blockchain.client import ArcClient
from blockchain.models import IndexerCursor
from blockchain.services import bytes_json
from jobs.models import ArcEvent, JobFundingSnapshot, Notification, VeyraJob
from wallets.models import CircleTransaction

logger = logging.getLogger(__name__)


def _enqueue_discovered_job(job_id: int) -> None:
    try:
        from workers.discovery import enqueue_job_created_fast_path

        enqueue_job_created_fast_path(job_id)
    except Exception:
        logger.exception("Worker JobCreated fast-path enqueue failed for job %s.", job_id)


EVENTS = [
    'JobCreated', 'JobClaimed', 'WorkSubmitted', 'JobCompleted', 'JobRejected',
    'JobCancelled', 'ClaimAbandoned', 'JobExpired',
]

@transaction.atomic
def apply_event(event_name, log):
    args = bytes_json(dict(log['args']))
    tx_hash = Web3.to_hex(log['transactionHash'])
    event, created = ArcEvent.objects.get_or_create(
        chain_id=settings.ARC_CHAIN_ID,
        contract_address=settings.VEYRA_CONTRACT_ADDRESS.lower(),
        transaction_hash=tx_hash,
        log_index=log['logIndex'],
        defaults={
            'block_number': log['blockNumber'],
            'event_name': event_name,
            'payload': args,
        },
    )
    if not created:
        return event

    CircleTransaction.objects.filter(arc_transaction_hash__iexact=tx_hash).update(
        status=CircleTransaction.Status.CONFIRMED, confirmed_at=timezone.now()
    )

    job_id = int(args['jobId'])
    if event_name == 'JobCreated':
        snapshot = JobFundingSnapshot.objects.select_related('draft', 'draft__client').filter(
            repository_hash=args['repositoryHash'],
            task_hash=args['taskHash'],
            policy_hash=args['policyHash'],
            budget_atomic=int(args['budget']),
            draft__client__wallet_accounts__address__iexact=args['client'],
        ).order_by('-locked_at').first()
        if snapshot:
            job, _ = VeyraJob.objects.update_or_create(
                onchain_job_id=job_id,
                defaults={
                    'client': snapshot.draft.client,
                    'draft': snapshot.draft,
                    'status': 'FUNDED',
                    'client_status': 'OPEN',
                    'client_address': args['client'].lower(),
                    'verifier_address': args['verifier'].lower(),
                    'invited_provider_address': args['invitedProvider'].lower(),
                    'budget_atomic': int(args['budget']),
                    'expires_at': int(args['expiresAt']),
                    'repository_hash': args['repositoryHash'],
                    'task_hash': args['taskHash'],
                    'policy_hash': args['policyHash'],
                    'creation_tx_hash': tx_hash,
                },
            )
            snapshot.draft.status = 'FUNDED'
            snapshot.draft.save(update_fields=['status', 'updated_at'])
            Notification.objects.create(
                user=snapshot.draft.client, event_type='JOB_FUNDED', title='Job funded',
                body=f'Job {job_id} is now open to Veyra agents.', resource_type='VeyraJob', resource_id=str(job_id)
            )
            transaction.on_commit(lambda job_id=job_id: _enqueue_discovered_job(job_id))
    else:
        job = VeyraJob.objects.filter(onchain_job_id=job_id).first()
        if not job:
            return event
        if event_name == 'JobClaimed':
            job.status, job.client_status = 'CLAIMED', 'AGENT_WORKING'
            job.provider_address = args['provider'].lower()
            job.claim_deadline = int(args['claimDeadline'])
        elif event_name == 'WorkSubmitted':
            job.status, job.client_status = 'SUBMITTED', 'UNDER_REVIEW'
            job.deliverable_hash = args['deliverableHash']
            job.commit_hash = args['commitHash']
            job.pull_request_number = int(args['pullRequestNumber'])
        elif event_name == 'JobCompleted':
            job.status, job.client_status = 'COMPLETED', 'COMPLETED'
            job.report_hash = args['reportHash']
            job.evidence_hash = args['evidenceHash']
        elif event_name == 'JobRejected':
            job.status, job.client_status = 'REJECTED', 'REFUNDED'
            job.report_hash = args['reportHash']
            job.evidence_hash = args['evidenceHash']
            job.rejection_reason_hash = args['reasonHash']
        elif event_name == 'JobCancelled':
            job.status, job.client_status = 'CANCELLED', 'CANCELLED'
        elif event_name == 'ClaimAbandoned':
            job.status, job.client_status = 'ABANDONED', 'REFUNDED'
        elif event_name == 'JobExpired':
            job.status, job.client_status = 'EXPIRED', 'REFUNDED'
        job.save()
        title_map = {
            'JobClaimed': 'Agent started work',
            'WorkSubmitted': 'Work submitted for review',
            'JobCompleted': 'Job completed',
            'JobRejected': 'Work rejected and refunded',
            'JobCancelled': 'Job cancelled',
            'ClaimAbandoned': 'Agent missed the deadline',
            'JobExpired': 'Job refunded',
        }
        Notification.objects.create(
            user=job.client, event_type=event_name.upper(), title=title_map.get(event_name, event_name),
            resource_type='VeyraJob', resource_id=str(job.onchain_job_id)
        )
    return event


def scan_once(to_block=None, chunk_size=1000):
    arc = ArcClient()
    arc.assert_chain()
    cursor, _ = IndexerCursor.objects.get_or_create(
        chain_id=settings.ARC_CHAIN_ID,
        contract_address=settings.VEYRA_CONTRACT_ADDRESS.lower(),
        defaults={'last_scanned_block': settings.ARC_INDEXER_START_BLOCK},
    )
    latest = to_block or arc.latest_block()
    start = cursor.last_scanned_block + 1
    if start > latest:
        return {'from_block': start, 'to_block': latest, 'events': 0}
    count = 0
    while start <= latest:
        end = min(start + chunk_size - 1, latest)
        for event_name in EVENTS:
            event_class = getattr(arc.contract.events, event_name)
            logs = event_class().get_logs(from_block=start, to_block=end)
            for log in logs:
                apply_event(event_name, log)
                count += 1
        cursor.last_scanned_block = end
        cursor.save(update_fields=['last_scanned_block', 'updated_at'])
        start = end + 1
    return {'from_block': cursor.last_scanned_block, 'to_block': latest, 'events': count}
