from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase

from web3 import Web3
from web3.exceptions import TransactionNotFound

from blockchain.client import (
    ARC_TESTNET_CHAIN_ID,
    ERC20_ABI,
    PUBLIC_ARC_RPC_FALLBACKS,
    ArcClient,
    ArcProviderPool,
    ArcRPCUnavailable,
    parse_arc_rpc_urls,
    redact_rpc_text,
    redact_rpc_url,
)


class HTTPFailure(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.response = SimpleNamespace(status_code=status_code, headers={})


class FakeEth:
    def __init__(self, *, chain_id=ARC_TESTNET_CHAIN_ID):
        self.chain_id = chain_id
        self.block_outcomes = []
        self.receipt_outcomes = []
        self.transaction_outcomes = []
        self.broadcast_outcomes = []
        self.broadcast_raw = []
        self.allowance_outcomes = []
        self.contract_abis = []

    @staticmethod
    def _next(outcomes, default):
        value = outcomes.pop(0) if outcomes else default
        if isinstance(value, Exception):
            raise value
        return value

    @property
    def block_number(self):
        return self._next(self.block_outcomes, 100)

    def get_transaction_receipt(self, tx_hash):
        return self._next(
            self.receipt_outcomes,
            TransactionNotFound(tx_hash),
        )

    def get_transaction(self, tx_hash):
        return self._next(
            self.transaction_outcomes,
            TransactionNotFound(tx_hash),
        )

    def send_raw_transaction(self, raw):
        value = bytes(raw)
        self.broadcast_raw.append(value)
        return self._next(self.broadcast_outcomes, Web3.keccak(value))

    def contract(self, *, address, abi):
        self.contract_abis.append(abi)
        owner = self

        class Functions:
            def allowance(self, account, spender):
                return self

            def call(self):
                return owner._next(owner.allowance_outcomes, 1_000_000)

        return SimpleNamespace(functions=Functions())


class FakeWeb3:
    def __init__(self, eth):
        self.eth = eth


def pool_for(eth_by_url, *, clock=lambda: 0.0, cooldown=30):
    return ArcProviderPool(
        list(eth_by_url),
        provider_factory=lambda url, timeout: FakeWeb3(eth_by_url[url]),
        cooldown_seconds=cooldown,
        clock=clock,
        sleeper=lambda seconds: None,
    )


class ArcRPCProviderPoolTests(TestCase):
    def test_usdc_allowance_failover_preserves_correct_abi_for_every_provider(self):
        providers = {
            url: FakeEth()
            for url in PUBLIC_ARC_RPC_FALLBACKS
        }
        for url in PUBLIC_ARC_RPC_FALLBACKS[:-1]:
            providers[url].allowance_outcomes = [HTTPFailure(503)]
        providers[PUBLIC_ARC_RPC_FALLBACKS[-1]].allowance_outcomes = [1_000_000]
        pool = pool_for(providers)
        expected_abi = deepcopy(ERC20_ABI)

        allowance = ArcClient(provider_pool=pool).allowance(
            "0x1111111111111111111111111111111111111111"
        )

        self.assertEqual(allowance, 1_000_000)
        self.assertEqual(ERC20_ABI, expected_abi)
        for url in PUBLIC_ARC_RPC_FALLBACKS:
            with self.subTest(provider=url):
                self.assertEqual(providers[url].contract_abis, [expected_abi])
                self.assertIs(providers[url].contract_abis[0], ERC20_ABI)

    def test_rpc_list_parses_commas_newlines_and_removes_duplicates(self):
        values = parse_arc_rpc_urls(
            "https://one.example/key,\nhttps://two.example/rpc\nhttps://one.example/key/",
            "https://legacy.example/rpc",
            fallbacks=("https://two.example/rpc",),
        )
        self.assertEqual(
            values,
            [
                "https://one.example/key",
                "https://two.example/rpc",
                "https://legacy.example/rpc",
            ],
        )

    def test_chain_id_is_validated_before_provider_is_used(self):
        wrong = FakeEth(chain_id=1)
        correct = FakeEth()
        pool = pool_for({"https://wrong": wrong, "https://correct": correct})

        value = pool.call("block", lambda provider: provider.w3.eth.block_number)

        self.assertEqual(value, 100)
        self.assertGreater(pool.providers[0].cooldown_until, 0)

    def test_all_wrong_chain_ids_are_rejected(self):
        pool = pool_for({"https://wrong": FakeEth(chain_id=1)})
        with self.assertRaises(ArcRPCUnavailable):
            pool.call("block", lambda provider: provider.w3.eth.block_number)
        self.assertGreater(pool.providers[0].cooldown_until, 0)

    def test_failover_after_429_timeout_and_5xx(self):
        for failure in (HTTPFailure(429), TimeoutError("timed out"), HTTPFailure(503)):
            with self.subTest(failure=failure):
                first = FakeEth()
                first.block_outcomes = [failure]
                second = FakeEth()
                second.block_outcomes = [222]
                pool = pool_for(
                    {"https://first": first, "https://second": second}
                )
                self.assertEqual(
                    pool.call(
                        "block", lambda provider: provider.w3.eth.block_number
                    ),
                    222,
                )

    def test_provider_recovers_after_cooldown(self):
        now = [0.0]
        first = FakeEth()
        first.block_outcomes = [HTTPFailure(429), 333]
        second = FakeEth()
        second.block_outcomes = [222, HTTPFailure(503)]
        pool = pool_for(
            {"https://first": first, "https://second": second},
            clock=lambda: now[0],
            cooldown=10,
        )
        self.assertEqual(
            pool.call("block", lambda provider: provider.w3.eth.block_number),
            222,
        )
        now[0] = 11
        self.assertEqual(
            pool.call("block", lambda provider: provider.w3.eth.block_number),
            333,
        )

    def test_private_rpc_url_is_redacted(self):
        value = redact_rpc_url(
            "https://user:secret@private.example/v2/private-token?apiKey=hidden"
        )
        self.assertEqual(value, "https://private.example")
        self.assertNotIn("secret", value)
        self.assertNotIn("private-token", value)
        self.assertNotIn("hidden", value)
        message = redact_rpc_text(
            "failed https://user:secret@private.example/v2/token?key=hidden"
        )
        self.assertEqual(message, "failed https://private.example")

    def test_same_signed_transaction_is_rebroadcast_after_429(self):
        raw = b"one-and-only-signed-transaction"
        expected = Web3.to_hex(Web3.keccak(raw))
        first = FakeEth()
        first.broadcast_outcomes = [HTTPFailure(429)]
        second = FakeEth()
        pool = pool_for(
            {"https://first": first, "https://second": second}
        )

        returned = pool.broadcast(raw, expected)

        self.assertEqual(returned, expected)
        self.assertEqual(first.broadcast_raw, [raw])
        self.assertEqual(second.broadcast_raw, [raw])

    def test_known_hash_prevents_duplicate_broadcast(self):
        raw = b"preserved"
        expected = Web3.to_hex(Web3.keccak(raw))
        provider = FakeEth()
        provider.transaction_outcomes = [{"hash": expected}]
        pool = pool_for({"https://only": provider})

        self.assertEqual(pool.broadcast(raw, expected), expected)
        self.assertEqual(provider.broadcast_raw, [])

    def test_contract_state_prevents_duplicate_broadcast_after_unknown_result(self):
        raw = b"preserved"
        expected = Web3.to_hex(Web3.keccak(raw))
        provider = FakeEth()
        pool = pool_for({"https://only": provider})

        returned = pool.broadcast(
            raw,
            expected,
            state_check=lambda selected: True,
        )

        self.assertEqual(returned, expected)
        self.assertEqual(provider.broadcast_raw, [])

    def test_receipt_polling_rotates_to_fallback_for_same_hash(self):
        first = FakeEth()
        first.receipt_outcomes = [HTTPFailure(429)]
        second = FakeEth()
        receipt = {"transactionHash": "0xabc", "status": 1}
        second.receipt_outcomes = [receipt]
        pool = pool_for(
            {"https://first": first, "https://second": second}
        )

        self.assertIs(pool.find_receipt("0xabc"), receipt)
