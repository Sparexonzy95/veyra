from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit

from django.conf import settings
from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound
from web3.logs import DISCARD


ABI_PATH = Path(__file__).resolve().parent / "abi" / "VeyraJobEscrow.json"
ARC_TESTNET_CHAIN_ID = 5042002
PUBLIC_ARC_RPC_FALLBACKS = (
    "https://rpc.drpc.testnet.arc.network",
    "https://rpc.quicknode.testnet.arc.network",
    "https://rpc.blockdaemon.testnet.arc.network",
    "https://rpc.testnet.arc.network",
)

T = TypeVar("T")
logger = logging.getLogger("veyra.arc_rpc")

ERC20_ABI = [
    {
        "type": "function",
        "name": "allowance",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

JOB_FIELDS = [
    "client",
    "invited_provider",
    "provider",
    "verifier",
    "budget",
    "expires_at",
    "claim_deadline",
    "repository_hash",
    "task_hash",
    "policy_hash",
    "deliverable_hash",
    "commit_hash",
    "pull_request_number",
    "report_hash",
    "evidence_hash",
    "rejection_reason_hash",
    "status",
    "created_at",
    "claimed_at",
    "submitted_at",
    "resolved_at",
]

JOB_STATUS = {
    0: "NONE",
    1: "FUNDED",
    2: "CLAIMED",
    3: "SUBMITTED",
    4: "COMPLETED",
    5: "REJECTED",
    6: "CANCELLED",
    7: "ABANDONED",
    8: "EXPIRED",
}

CLIENT_STATUS = {
    "FUNDED": "OPEN",
    "CLAIMED": "AGENT_WORKING",
    "SUBMITTED": "UNDER_REVIEW",
    "COMPLETED": "COMPLETED",
    "REJECTED": "REFUNDED",
    "CANCELLED": "CANCELLED",
    "ABANDONED": "REFUNDED",
    "EXPIRED": "REFUNDED",
}


class ArcRPCUnavailable(RuntimeError):
    """Safe, credential-free error returned after all providers fail."""


class ArcChainMismatch(RuntimeError):
    pass


def parse_arc_rpc_urls(
    rpc_urls: str | None,
    legacy_rpc_url: str | None,
    *,
    fallbacks: tuple[str, ...] = PUBLIC_ARC_RPC_FALLBACKS,
) -> list[str]:
    """Parse configured URLs and append safe public fallbacks in priority order."""
    configured = [
        value.strip()
        for value in re.split(r"[\s,]+", str(rpc_urls or ""))
        if value.strip()
    ]
    legacy = str(legacy_rpc_url or "").strip()
    ordered = [*configured, *([legacy] if legacy else []), *fallbacks]
    result: list[str] = []
    seen: set[str] = set()
    for value in ordered:
        normalized = value.rstrip("/")
        if not normalized or normalized in seen:
            continue
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Arc RPC endpoints must be valid HTTP(S) URLs.")
        seen.add(normalized)
        result.append(normalized)
    if not result:
        raise ValueError("At least one Arc RPC endpoint must be configured.")
    return result


def redact_rpc_url(url: str) -> str:
    """Return an origin-only provider label, never credentials/path/query data."""
    try:
        parsed = urlsplit(str(url or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "[REDACTED_ARC_RPC]"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    except Exception:
        return "[REDACTED_ARC_RPC]"


def redact_rpc_text(value: str) -> str:
    return re.sub(
        r"https?://[^\s<>'\"]+",
        lambda match: redact_rpc_url(match.group(0).rstrip(".,);]")),
        str(value or ""),
        flags=re.IGNORECASE,
    )


def _retryable_rpc_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 429 or (
        isinstance(status_code, int) and 500 <= status_code <= 599
    ):
        return True
    text = str(exc or "").casefold()
    return any(
        marker in text
        for marker in (
            "429",
            "too many requests",
            "rate limit",
            "timed out",
            "timeout",
            "connection reset",
            "connection aborted",
            "connection refused",
            "name resolution",
            "temporarily unavailable",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        )
    )


@dataclass
class ArcProvider:
    url: str
    w3: Web3
    chain_validated: bool = False
    cooldown_until: float = 0.0
    failures: int = 0

    @property
    def label(self) -> str:
        return redact_rpc_url(self.url)


class ArcProviderPool:
    """Process-shared Arc RPC health, cooldown, validation and failover state."""

    def __init__(
        self,
        urls: list[str],
        *,
        chain_id: int = ARC_TESTNET_CHAIN_ID,
        timeout: float = 20,
        cooldown_seconds: float = 30,
        provider_factory: Callable[[str, float], Web3] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if int(chain_id) != ARC_TESTNET_CHAIN_ID:
            raise ValueError(
                f"Arc Testnet chain ID must be {ARC_TESTNET_CHAIN_ID}."
            )
        factory = provider_factory or (
            lambda url, value: Web3(
                Web3.HTTPProvider(url, request_kwargs={"timeout": value})
            )
        )
        self.providers = [
            ArcProvider(url=url, w3=factory(url, timeout)) for url in urls
        ]
        self.chain_id = int(chain_id)
        self.cooldown_seconds = max(0.1, float(cooldown_seconds))
        self.clock = clock
        self.sleeper = sleeper
        self._active_index = 0
        self._lock = threading.RLock()

    def _ordered_indexes(self) -> list[int]:
        # Always restore configured priority after a provider's cooldown. While
        # it is cooling down `_available_indexes` skips it immediately.
        return list(range(len(self.providers)))

    def _available_indexes(self) -> list[int]:
        now = self.clock()
        return [
            index
            for index in self._ordered_indexes()
            if self.providers[index].cooldown_until <= now
        ]

    def _mark_failure(self, index: int, exc: Exception, operation: str) -> None:
        provider = self.providers[index]
        with self._lock:
            provider.failures += 1
            provider.chain_validated = False
            provider.cooldown_until = self.clock() + self.cooldown_seconds
        logger.warning(
            "arc_rpc_provider_cooldown operation=%s provider=%s reason=%s",
            operation,
            provider.label,
            exc.__class__.__name__,
        )

    def _mark_success(self, index: int) -> None:
        provider = self.providers[index]
        with self._lock:
            provider.failures = 0
            provider.cooldown_until = 0.0
            self._active_index = index

    def _validate_chain(self, index: int) -> ArcProvider:
        provider = self.providers[index]
        if provider.chain_validated:
            return provider
        actual = int(provider.w3.eth.chain_id)
        if actual != self.chain_id:
            raise ArcChainMismatch(
                f"Arc RPC chain mismatch: expected {self.chain_id}, got {actual}."
            )
        provider.chain_validated = True
        return provider

    def call(self, operation: str, callback: Callable[[ArcProvider], T]) -> T:
        available = self._available_indexes()
        if not available:
            raise ArcRPCUnavailable(
                "Arc RPC providers are cooling down; automatic retry is scheduled."
            )
        last_error: Exception | None = None
        for index in available:
            try:
                provider = self._validate_chain(index)
                value = callback(provider)
                self._mark_success(index)
                return value
            except Exception as exc:
                last_error = exc
                if isinstance(exc, ArcChainMismatch) or _retryable_rpc_error(exc):
                    self._mark_failure(index, exc, operation)
                    continue
                raise
        raise ArcRPCUnavailable(
            "Arc RPC providers are temporarily unavailable; automatic failover exhausted."
        ) from None

    def find_receipt(self, tx_hash: str):
        """Check the same hash across healthy providers before reporting pending."""
        available = self._available_indexes()
        if not available:
            raise ArcRPCUnavailable(
                "Arc RPC providers are cooling down; receipt polling will retry."
            )
        last_error: Exception | None = None
        saw_not_found = False
        for index in available:
            try:
                provider = self._validate_chain(index)
                receipt = provider.w3.eth.get_transaction_receipt(tx_hash)
                self._mark_success(index)
                return receipt
            except TransactionNotFound:
                saw_not_found = True
                continue
            except Exception as exc:
                last_error = exc
                if isinstance(exc, ArcChainMismatch) or _retryable_rpc_error(exc):
                    self._mark_failure(index, exc, "get_transaction_receipt")
                    continue
                raise
        if saw_not_found:
            return None
        raise ArcRPCUnavailable(
            "Arc RPC providers are temporarily unavailable while polling a receipt."
        ) from None

    def broadcast(
        self,
        raw_transaction: bytes,
        expected_hash: str,
        *,
        state_check: Callable[[ArcProvider], bool] | None = None,
    ) -> str:
        """Rebroadcast identical signed bytes; never rebuild a transaction."""
        available = self._available_indexes()
        if not available:
            raise ArcRPCUnavailable(
                "Arc RPC providers are cooling down; signed transaction is preserved."
            )
        last_error: Exception | None = None
        for index in available:
            try:
                provider = self._validate_chain(index)
                try:
                    provider.w3.eth.get_transaction(expected_hash)
                    self._mark_success(index)
                    return expected_hash
                except TransactionNotFound:
                    pass
                if state_check is not None and state_check(provider):
                    self._mark_success(index)
                    return expected_hash
                returned = Web3.to_hex(
                    provider.w3.eth.send_raw_transaction(raw_transaction)
                )
                if returned.casefold() != expected_hash.casefold():
                    raise RuntimeError(
                        "Arc RPC returned a transaction hash that does not match "
                        "the preserved signed transaction."
                    )
                self._mark_success(index)
                return expected_hash
            except Exception as exc:
                last_error = exc
                if isinstance(exc, ArcChainMismatch) or _retryable_rpc_error(exc):
                    self._mark_failure(index, exc, "send_raw_transaction")
                    continue
                raise
        raise ArcRPCUnavailable(
            "Arc broadcast result is unknown; signed transaction and hash are preserved."
        ) from None


_POOL_LOCK = threading.Lock()
_SHARED_POOL: ArcProviderPool | None = None
_SHARED_POOL_SIGNATURE: tuple[Any, ...] | None = None


def get_arc_provider_pool() -> ArcProviderPool:
    global _SHARED_POOL, _SHARED_POOL_SIGNATURE
    urls = parse_arc_rpc_urls(
        getattr(settings, "ARC_RPC_URLS", ""),
        getattr(settings, "ARC_RPC_URL", ""),
    )
    signature = (
        tuple(urls),
        int(getattr(settings, "ARC_CHAIN_ID", ARC_TESTNET_CHAIN_ID)),
        float(getattr(settings, "ARC_RPC_TIMEOUT_SECONDS", 20)),
        float(getattr(settings, "ARC_RPC_COOLDOWN_SECONDS", 30)),
    )
    with _POOL_LOCK:
        if _SHARED_POOL is None or _SHARED_POOL_SIGNATURE != signature:
            _SHARED_POOL = ArcProviderPool(
                urls,
                chain_id=signature[1],
                timeout=signature[2],
                cooldown_seconds=signature[3],
            )
            _SHARED_POOL_SIGNATURE = signature
        return _SHARED_POOL


def reset_arc_provider_pool() -> None:
    """Testing hook; production callers share the cached pool."""
    global _SHARED_POOL, _SHARED_POOL_SIGNATURE
    with _POOL_LOCK:
        _SHARED_POOL = None
        _SHARED_POOL_SIGNATURE = None


class ArcClient:
    def __init__(self, *, provider_pool: ArcProviderPool | None = None):
        self.pool = provider_pool or get_arc_provider_pool()
        artifact = json.loads(ABI_PATH.read_text())
        self.abi = artifact["abi"]
        # Provider-free contracts are used only for ABI encoding and receipt
        # decoding. Every network operation goes through `self.pool`.
        local = Web3()
        self.contract = local.eth.contract(
            address=Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS),
            abi=self.abi,
        )
        self.usdc = local.eth.contract(
            address=Web3.to_checksum_address(settings.ARC_USDC_ADDRESS),
            abi=ERC20_ABI,
        )

    def _contract_for(self, provider: ArcProvider):
        return provider.w3.eth.contract(
            address=Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS),
            abi=self.abi,
        )

    def _usdc_for(self, provider: ArcProvider):
        return provider.w3.eth.contract(
            address=Web3.to_checksum_address(settings.ARC_USDC_ADDRESS),
            abi=ERC20_ABI,
        )

    def assert_chain(self):
        return self.pool.call("assert_chain", lambda provider: provider.w3.eth.chain_id)

    @staticmethod
    def account_from_key(private_key: str):
        return Account.from_key(private_key)

    def contract_call(self, function_name: str, *args):
        return self.pool.call(
            function_name,
            lambda provider: getattr(
                self._contract_for(provider).functions, function_name
            )(*args).call(),
        )

    def provider_contract_call(
        self, provider: ArcProvider, function_name: str, *args
    ):
        return getattr(
            self._contract_for(provider).functions, function_name
        )(*args).call()

    def estimate_contract_gas(
        self, function_name: str, args: tuple[Any, ...], transaction: dict
    ) -> int:
        return int(
            self.pool.call(
                f"estimate_{function_name}",
                lambda provider: getattr(
                    self._contract_for(provider).functions, function_name
                )(*args).estimate_gas(transaction),
            )
        )

    def build_contract_transaction(
        self,
        function_name: str,
        args: tuple[Any, ...],
        transaction: dict,
    ) -> dict:
        return self.pool.call(
            f"build_{function_name}",
            lambda provider: getattr(
                self._contract_for(provider).functions, function_name
            )(*args).build_transaction(transaction),
        )

    def get_transaction_count(self, address: str, block: str = "pending") -> int:
        return int(
            self.pool.call(
                "get_transaction_count",
                lambda provider: provider.w3.eth.get_transaction_count(address, block),
            )
        )

    def gas_price(self) -> int:
        return int(
            self.pool.call("gas_price", lambda provider: provider.w3.eth.gas_price)
        )

    def get_balance(self, address: str) -> int:
        return int(
            self.pool.call(
                "get_balance", lambda provider: provider.w3.eth.get_balance(address)
            )
        )

    @staticmethod
    def signed_transaction_bytes(signed) -> bytes:
        raw = getattr(signed, "raw_transaction", None)
        if raw is None:
            raw = getattr(signed, "rawTransaction", None)
        if raw is None:
            raise RuntimeError("The Web3 signer did not return a raw transaction.")
        return bytes(raw)

    @staticmethod
    def signed_transaction_hash(raw_transaction: bytes) -> str:
        return Web3.to_hex(Web3.keccak(raw_transaction))

    def broadcast_signed_transaction(
        self,
        raw_transaction: bytes,
        expected_hash: str | None = None,
        *,
        state_check: Callable[[ArcProvider], bool] | None = None,
    ) -> str:
        calculated = self.signed_transaction_hash(raw_transaction)
        if expected_hash and calculated.casefold() != expected_hash.casefold():
            raise ValueError(
                "Expected transaction hash does not match signed transaction bytes."
            )
        return self.pool.broadcast(
            raw_transaction,
            calculated,
            state_check=state_check,
        )

    def encode_approve(self, amount_atomic: int) -> str:
        return self.usdc.encode_abi(
            "approve",
            args=[
                Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS),
                amount_atomic,
            ],
        )

    def encode_create_job(
        self,
        *,
        invited_provider: str,
        verifier: str,
        budget_atomic: int,
        expires_at: int,
        repository_hash: str,
        task_hash: str,
        policy_hash: str,
    ) -> str:
        return self.contract.encode_abi(
            "createJob",
            args=[
                Web3.to_checksum_address(invited_provider),
                Web3.to_checksum_address(verifier),
                budget_atomic,
                expires_at,
                bytes.fromhex(repository_hash.removeprefix("0x")),
                bytes.fromhex(task_hash.removeprefix("0x")),
                bytes.fromhex(policy_hash.removeprefix("0x")),
            ],
        )

    def encode_client_action(self, function_name: str, job_id: int) -> str:
        if function_name not in {
            "cancelUnclaimedJob",
            "refundAbandonedClaim",
            "claimExpiredRefund",
        }:
            raise ValueError("Unsupported client action.")
        return self.contract.encode_abi(function_name, args=[job_id])

    def allowance(self, owner: str) -> int:
        return int(
            self.pool.call(
                "allowance",
                lambda provider: self._usdc_for(provider)
                .functions.allowance(
                    Web3.to_checksum_address(owner),
                    Web3.to_checksum_address(settings.VEYRA_CONTRACT_ADDRESS),
                )
                .call(),
            )
        )

    def is_verifier_authorised(self, address: str) -> bool:
        return bool(
            self.contract_call(
                "authorisedVerifiers", Web3.to_checksum_address(address)
            )
        )

    def is_agent_authorised(self, address: str) -> bool:
        return bool(
            self.contract_call(
                "authorisedAgents", Web3.to_checksum_address(address)
            )
        )

    def is_paused(self) -> bool:
        return bool(self.contract_call("paused"))

    def get_job(self, job_id: int) -> dict:
        raw = self.contract_call("getJob", job_id)
        job = dict(zip(JOB_FIELDS, raw, strict=True))
        job["job_id"] = job_id
        for key in [
            "repository_hash",
            "task_hash",
            "policy_hash",
            "deliverable_hash",
            "commit_hash",
            "report_hash",
            "evidence_hash",
            "rejection_reason_hash",
        ]:
            job[key] = Web3.to_hex(job[key])
        job["status_code"] = job["status"]
        job["status"] = JOB_STATUS.get(job["status"], "UNKNOWN")
        job["client_status"] = CLIENT_STATUS.get(job["status"], job["status"])
        for key in ["client", "invited_provider", "provider", "verifier"]:
            job[key] = job[key].lower()
        return job

    def verification_deadline(self, job_id: int) -> int:
        return int(self.contract_call("verificationDeadline", job_id))

    def compute_deliverable_hash(
        self, job_id: int, commit_hash: str, pull_request_number: int
    ) -> str:
        if not (
            isinstance(commit_hash, str)
            and commit_hash.startswith("0x")
            and len(commit_hash) == 66
        ):
            raise ValueError("Commit hash must be a 32-byte hex value.")
        value = self.contract_call(
            "computeDeliverableHash",
            int(job_id),
            bytes.fromhex(commit_hash.removeprefix("0x")),
            int(pull_request_number),
        )
        return Web3.to_hex(value)

    def transaction(self, tx_hash: str):
        return self.pool.call(
            "get_transaction",
            lambda provider: provider.w3.eth.get_transaction(tx_hash),
        )

    def transaction_receipt(self, tx_hash: str):
        receipt = self.pool.find_receipt(tx_hash)
        if receipt is None:
            raise TransactionNotFound(tx_hash)
        return receipt

    def transaction_receipt_or_none(self, tx_hash: str):
        return self.pool.find_receipt(tx_hash)

    def wait_for_transaction_receipt(
        self, tx_hash: str, *, timeout: float = 120, poll_latency: float = 3
    ):
        deadline = time.monotonic() + max(0.1, float(timeout))
        while True:
            receipt = self.transaction_receipt_or_none(tx_hash)
            if receipt is not None:
                return receipt
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Arc transaction receipt is still pending; polling will resume."
                )
            time.sleep(max(0.05, float(poll_latency)))

    def decode_receipt_event(self, event_name: str, receipt):
        event_class = getattr(self.contract.events, event_name, None)
        if event_class is None:
            raise ValueError(f"Unsupported contract event: {event_name}")
        expected_address = self.contract.address.lower()
        public_receipt = dict(receipt)
        logs = receipt.get("logs", []) if isinstance(receipt, dict) else getattr(
            receipt, "logs", []
        )
        public_receipt["logs"] = [
            log
            for log in logs
            if str(
                (
                    log.get("address")
                    if isinstance(log, dict)
                    else getattr(log, "address", "")
                )
                or ""
            ).lower()
            == expected_address
        ]
        return list(
            event_class().process_receipt(public_receipt, errors=DISCARD)
        )

    def event_logs(self, event_name: str, *, from_block: int, to_block: int):
        return self.pool.call(
            f"event_logs_{event_name}",
            lambda provider: getattr(
                self._contract_for(provider).events, event_name
            )().get_logs(from_block=from_block, to_block=to_block),
        )

    def latest_block(self) -> int:
        return int(
            self.pool.call(
                "latest_block", lambda provider: provider.w3.eth.block_number
            )
        )
