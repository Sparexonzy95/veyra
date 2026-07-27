import json
import time
from functools import cached_property
from pathlib import Path
from typing import Callable, TypeVar
from django.conf import settings
from web3 import Web3
from web3.logs import DISCARD
from web3.exceptions import ContractLogicError, TransactionNotFound

ABI_PATH = Path(__file__).resolve().parent / 'abi' / 'VeyraJobEscrow.json'

T = TypeVar('T')

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
        self._last_rpc_at = 0.0
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

    @staticmethod
    def _retryable_rpc_error(exc: Exception) -> bool:
        response = getattr(exc, 'response', None)
        status_code = getattr(response, 'status_code', None)
        if status_code in {429, 500, 502, 503, 504}:
            return True
        text = str(exc or '').lower()
        return any(
            marker in text
            for marker in (
                '429',
                'too many requests',
                'rate limit',
                'timed out',
                'timeout',
                'connection reset',
                'connection aborted',
                'temporarily unavailable',
                'bad gateway',
                'service unavailable',
                'gateway timeout',
            )
        )

    def _rpc_call(self, callback: Callable[[], T]) -> T:
        attempts = max(1, int(getattr(settings, 'ARC_RPC_RETRY_ATTEMPTS', 5)))
        base_delay = max(0.25, float(getattr(settings, 'ARC_RPC_RETRY_BASE_SECONDS', 1.0)))
        last_error: Exception | None = None
        minimum_interval = max(
            0.0,
            float(getattr(settings, 'ARC_RPC_MIN_INTERVAL_SECONDS', 0.35)),
        )
        for attempt in range(attempts):
            elapsed = time.monotonic() - self._last_rpc_at
            if elapsed < minimum_interval:
                time.sleep(minimum_interval - elapsed)
            self._last_rpc_at = time.monotonic()
            try:
                return callback()
            except Exception as exc:
                last_error = exc
                if not self._retryable_rpc_error(exc) or attempt >= attempts - 1:
                    raise
                response = getattr(exc, 'response', None)
                headers = getattr(response, 'headers', {}) or {}
                retry_after = headers.get('Retry-After')
                try:
                    delay = float(retry_after) if retry_after is not None else base_delay * (2 ** attempt)
                except (TypeError, ValueError):
                    delay = base_delay * (2 ** attempt)
                time.sleep(min(max(delay, 0.25), 10.0))
        assert last_error is not None
        raise last_error

    def assert_chain(self):
        actual = self._rpc_call(lambda: self.w3.eth.chain_id)
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
        return self._rpc_call(
            lambda: self.usdc.functions.allowance(
                Web3.to_checksum_address(owner),
                Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS),
            ).call()
        )

    def is_verifier_authorised(self, address: str) -> bool:
        return bool(
            self._rpc_call(
                lambda: self.contract.functions.authorisedVerifiers(
                    Web3.to_checksum_address(address)
                ).call()
            )
        )

    def is_agent_authorised(self, address: str) -> bool:
        return bool(
            self._rpc_call(
                lambda: self.contract.functions.authorisedAgents(
                    Web3.to_checksum_address(address)
                ).call()
            )
        )

    def is_paused(self) -> bool:
        return bool(self._rpc_call(lambda: self.contract.functions.paused().call()))

    def get_job(self, job_id: int) -> dict:
        raw = self._rpc_call(lambda: self.contract.functions.getJob(job_id).call())
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
        return int(
            self._rpc_call(
                lambda: self.contract.functions.verificationDeadline(job_id).call()
            )
        )

    def compute_deliverable_hash(self, job_id: int, commit_hash: str, pull_request_number: int) -> str:
        if not (isinstance(commit_hash, str) and commit_hash.startswith('0x') and len(commit_hash) == 66):
            raise ValueError('Commit hash must be a 32-byte hex value.')
        value = self._rpc_call(
            lambda: self.contract.functions.computeDeliverableHash(
                int(job_id),
                bytes.fromhex(commit_hash.removeprefix('0x')),
                int(pull_request_number),
            ).call()
        )
        return Web3.to_hex(value)

    def transaction(self, tx_hash: str):
        return self._rpc_call(lambda: self.w3.eth.get_transaction(tx_hash))

    def transaction_receipt(self, tx_hash: str):
        return self._rpc_call(lambda: self.w3.eth.get_transaction_receipt(tx_hash))

    def transaction_receipt_or_none(self, tx_hash: str):
        try:
            return self.transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None

    def decode_receipt_event(self, event_name: str, receipt):
        event_class = getattr(self.contract.events, event_name, None)
        if event_class is None:
            raise ValueError(f'Unsupported contract event: {event_name}')

        # Circle SCA transactions emit account-abstraction and token logs in the
        # same receipt. Filter to this escrow contract before decoding and
        # silently discard non-matching topics so unattended workers do not
        # produce noisy MismatchedABI warnings.
        expected_address = self.contract.address.lower()
        if isinstance(receipt, dict):
            public_receipt = dict(receipt)
            logs = receipt.get('logs', [])
        else:
            public_receipt = dict(receipt)
            logs = getattr(receipt, 'logs', [])
        public_receipt['logs'] = [
            log for log in logs
            if str((log.get('address') if isinstance(log, dict) else getattr(log, 'address', '')) or '').lower()
            == expected_address
        ]
        return list(event_class().process_receipt(public_receipt, errors=DISCARD))

    def latest_block(self) -> int:
        return self._rpc_call(lambda: self.w3.eth.block_number)
