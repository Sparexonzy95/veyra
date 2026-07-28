from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from web3 import Web3

from blockchain.client import ArcClient, ERC20_ABI
from blockchain.services import available_client_action


def erc20_function(name):
    return next(item for item in ERC20_ABI if item["name"] == name)


class ContractEncodingTests(SimpleTestCase):
    def test_allowance_returns_uint256_and_approve_returns_bool(self):
        self.assertEqual(
            erc20_function("allowance")["outputs"],
            [{"name": "", "type": "uint256"}],
        )
        self.assertEqual(
            erc20_function("approve")["outputs"],
            [{"name": "", "type": "bool"}],
        )

    def test_one_usdc_allowance_decodes_as_uint256(self):
        encoded = (1_000_000).to_bytes(32, byteorder="big")
        decoded = Web3().codec.decode(["uint256"], encoded)

        self.assertEqual(decoded, (1_000_000,))

    def test_arc_client_allowance_returns_integer(self):
        pool = MagicMock()
        provider = SimpleNamespace()
        pool.call.side_effect = lambda operation, callback: callback(provider)
        arc = ArcClient(provider_pool=pool)
        contract = MagicMock()
        contract.functions.allowance.return_value.call.return_value = 1_000_000

        with patch.object(arc, "_usdc_for", return_value=contract):
            allowance = arc.allowance(
                "0x1111111111111111111111111111111111111111"
            )

        self.assertEqual(allowance, 1_000_000)
        self.assertIsInstance(allowance, int)
        pool.call.assert_called_once()

    def test_contract_encoding_does_not_mutate_erc20_abi(self):
        before = deepcopy(ERC20_ABI)
        ArcClient().encode_approve(1_000_000)
        self.assertEqual(ERC20_ABI, before)

    def test_deployed_function_selectors(self):
        arc = ArcClient()
        self.assertTrue(arc.encode_approve(1).startswith('0x095ea7b3'))
        self.assertTrue(arc.encode_create_job(
            invited_provider='0x0000000000000000000000000000000000000000',
            verifier='0x0EdBC6F8506e72478CE78a4AE934C7b21cb7050A',
            budget_atomic=1_000_000,
            expires_at=2_000_000_000,
            repository_hash='0x' + '11' * 32,
            task_hash='0x' + '22' * 32,
            policy_hash='0x' + '33' * 32,
        ).startswith('0xbb0a450e'))
        self.assertTrue(arc.encode_client_action('cancelUnclaimedJob', 1).startswith('0x77ebf540'))

class ContextualActionTests(SimpleTestCase):
    def test_funded_job_can_cancel_before_expiry(self):
        action = available_client_action({'status': 'FUNDED', 'expires_at': 9_999_999_999, 'job_id': 1})
        self.assertEqual(action['contract_function'], 'cancelUnclaimedJob')

    def test_claimed_job_refunds_after_deadline(self):
        action = available_client_action({'status': 'CLAIMED', 'claim_deadline': 1, 'job_id': 1})
        self.assertEqual(action['contract_function'], 'refundAbandonedClaim')
