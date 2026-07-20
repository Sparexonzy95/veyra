import json
from functools import cached_property
from pathlib import Path
from django.conf import settings
from web3 import Web3
from web3.exceptions import ContractLogicError, TransactionNotFound

ABI_PATH = Path(__file__).resolve().parent / 'abi' / 'VeyraJobEscrow.json'

ERC20_ABI = [
    {
        'type': 'function', 'name': 'allowance', 'stateMutability': 'view',
        'inputs': [{'name': 'owner', 'type': 'address'}, {'name': 'spender', 'type': 'address'}],
        'outputs': [{'name': '', 'type': 'uint256'}],
    },
    {
        'type': 'function', 'name': 'approve', 'stateMutability': 'nonpayable',
        'inputs': [{'name': 'spender', 'type': 'address'}, {'name': 'amount', 'type': 'uint256'}],
        'outputs': [{'name': '', 'type': 'bool'}],
    },
]

JOB_FIELDS = [
    'client', 'invited_provider', 'provider', 'verifier', 'budget', 'expires_at', 'claim_deadline',
    'repository_hash', 'task_hash', 'policy_hash', 'deliverable_hash', 'commit_hash',
    'pull_request_number', 'report_hash', 'evidence_hash', 'rejection_reason_hash', 'status',
    'created_at', 'claimed_at', 'submitted_at', 'resolved_at',
]

JOB_STATUS = {
    0: 'NONE', 1: 'FUNDED', 2: 'CLAIMED', 3: 'SUBMITTED', 4: 'COMPLETED',
    5: 'REJECTED', 6: 'CANCELLED', 7: 'ABANDONED', 8: 'EXPIRED',
}

CLIENT_STATUS = {
    'FUNDED': 'OPEN',
    'CLAIMED': 'AGENT_WORKING',
    'SUBMITTED': 'UNDER_REVIEW',
    'COMPLETED': 'COMPLETED',
    'REJECTED': 'REFUNDED',
    'CANCELLED': 'CANCELLED',
    'ABANDONED': 'REFUNDED',
    'EXPIRED': 'REFUNDED',
}

class ArcClient:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(settings.ARC_RPC_URL, request_kwargs={'timeout': 20}))
        artifact = json.loads(ABI_PATH.read_text())
        self.abi = artifact['abi']
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS),
            abi=self.abi,
        )
        self.usdc = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.ARC_USDC_ADDRESS),
            abi=ERC20_ABI,
        )

    def assert_chain(self):
        actual = self.w3.eth.chain_id
        if actual != settings.ARC_CHAIN_ID:
            raise RuntimeError(f'Arc RPC chain mismatch: expected {settings.ARC_CHAIN_ID}, got {actual}.')

    def encode_approve(self, amount_atomic: int) -> str:
        return self.usdc.encode_abi('approve', args=[Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS), amount_atomic])

    def encode_create_job(self, *, invited_provider: str, verifier: str, budget_atomic: int, expires_at: int, repository_hash: str, task_hash: str, policy_hash: str) -> str:
        return self.contract.encode_abi('createJob', args=[
            Web3.to_checksum_address(invited_provider),
            Web3.to_checksum_address(verifier),
            budget_atomic,
            expires_at,
            bytes.fromhex(repository_hash.removeprefix('0x')),
            bytes.fromhex(task_hash.removeprefix('0x')),
            bytes.fromhex(policy_hash.removeprefix('0x')),
        ])

    def encode_client_action(self, function_name: str, job_id: int) -> str:
        if function_name not in {'cancelUnclaimedJob', 'refundAbandonedClaim', 'claimExpiredRefund'}:
            raise ValueError('Unsupported client action.')
        return self.contract.encode_abi(function_name, args=[job_id])

    def allowance(self, owner: str) -> int:
        return self.usdc.functions.allowance(
            Web3.to_checksum_address(owner),
            Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS),
        ).call()

    def is_verifier_authorised(self, address: str) -> bool:
        return bool(self.contract.functions.authorisedVerifiers(Web3.to_checksum_address(address)).call())

    def is_agent_authorised(self, address: str) -> bool:
        return bool(self.contract.functions.authorisedAgents(Web3.to_checksum_address(address)).call())

    def is_paused(self) -> bool:
        return bool(self.contract.functions.paused().call())

    def get_job(self, job_id: int) -> dict:
        raw = self.contract.functions.getJob(job_id).call()
        job = dict(zip(JOB_FIELDS, raw, strict=True))
        job['job_id'] = job_id
        for key in ['repository_hash', 'task_hash', 'policy_hash', 'deliverable_hash', 'commit_hash', 'report_hash', 'evidence_hash', 'rejection_reason_hash']:
            value = job[key]
            job[key] = Web3.to_hex(value)
        job['status_code'] = job['status']
        job['status'] = JOB_STATUS.get(job['status'], 'UNKNOWN')
        job['client_status'] = CLIENT_STATUS.get(job['status'], job['status'])
        for key in ['client', 'invited_provider', 'provider', 'verifier']:
            job[key] = job[key].lower()
        return job

    def verification_deadline(self, job_id: int) -> int:
        return int(self.contract.functions.verificationDeadline(job_id).call())

    def transaction(self, tx_hash: str):
        return self.w3.eth.get_transaction(tx_hash)

    def transaction_receipt(self, tx_hash: str):
        return self.w3.eth.get_transaction_receipt(tx_hash)

    def transaction_receipt_or_none(self, tx_hash: str):
        try:
            return self.transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None

    def decode_receipt_event(self, event_name: str, receipt):
        event_class = getattr(self.contract.events, event_name, None)
        if event_class is None:
            raise ValueError(f'Unsupported contract event: {event_name}')
        return list(event_class().process_receipt(receipt))

    def latest_block(self) -> int:
        return self.w3.eth.block_number
