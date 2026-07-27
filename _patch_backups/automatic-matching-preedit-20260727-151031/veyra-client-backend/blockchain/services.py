from django.utils import timezone
from web3 import Web3
from blockchain.client import ArcClient


def available_client_action(onchain_job: dict):
    now = int(timezone.now().timestamp())
    status = onchain_job['status']
    if status == 'FUNDED':
        if now > onchain_job['expires_at']:
            return {'code': 'CLAIM_REFUND', 'contract_function': 'claimExpiredRefund', 'label': 'Claim Refund'}
        return {'code': 'CANCEL_JOB', 'contract_function': 'cancelUnclaimedJob', 'label': 'Cancel Job'}
    if status == 'CLAIMED' and now > onchain_job['claim_deadline']:
        return {'code': 'CLAIM_REFUND', 'contract_function': 'refundAbandonedClaim', 'label': 'Claim Refund'}
    if status == 'SUBMITTED':
        try:
            deadline = ArcClient().verification_deadline(onchain_job['job_id'])
        except Exception:
            deadline = 0
        if deadline and now > deadline:
            return {'code': 'CLAIM_REFUND', 'contract_function': 'claimExpiredRefund', 'label': 'Claim Refund'}
    return None


def bytes_json(value):
    if isinstance(value, (bytes, bytearray)):
        return Web3.to_hex(value)
    if isinstance(value, dict):
        return {key: bytes_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [bytes_json(item) for item in value]
    return value
