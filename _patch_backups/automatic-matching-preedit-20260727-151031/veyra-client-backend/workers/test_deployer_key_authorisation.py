from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from web3 import Web3

from workers.contract_authorisation import (
    ContractAuthorisationError,
    _owner_signer,
)


class DeployerKeyContractAuthorisationTests(SimpleTestCase):
    @override_settings(
        VEYRA_CONTRACT_OWNER_PRIVATE_KEY=(
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a84"
            "11a4f2d7f6eec8f9"
        ),
        VEYRA_CONTRACT_OWNER_WALLET_ADDRESS="",
    )
    def test_owner_signer_must_match_onchain_owner(self):
        arc = Mock()
        account = Web3().eth.account.from_key(
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a84"
            "11a4f2d7f6eec8f9"
        )
        arc.w3.eth.account.from_key.return_value = account
        arc.contract.functions.owner.return_value.call.return_value = account.address

        signer = _owner_signer(arc)

        self.assertEqual(
            Web3.to_checksum_address(signer.address),
            Web3.to_checksum_address(account.address),
        )

    @override_settings(
        VEYRA_CONTRACT_OWNER_PRIVATE_KEY=(
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a84"
            "11a4f2d7f6eec8f9"
        ),
        VEYRA_CONTRACT_OWNER_WALLET_ADDRESS="",
    )
    def test_wrong_owner_is_rejected(self):
        arc = Mock()
        account = Web3().eth.account.from_key(
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a84"
            "11a4f2d7f6eec8f9"
        )
        arc.w3.eth.account.from_key.return_value = account
        arc.contract.functions.owner.return_value.call.return_value = (
            "0x1111111111111111111111111111111111111111"
        )

        with self.assertRaisesMessage(
            ContractAuthorisationError,
            "is not the deployed contract owner",
        ):
            _owner_signer(arc)
