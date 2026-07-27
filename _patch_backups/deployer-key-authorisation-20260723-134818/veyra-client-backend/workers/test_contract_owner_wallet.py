from unittest.mock import Mock
import uuid

from django.test import SimpleTestCase, override_settings

from workers.contract_authorisation import (
    CircleContractOwnerClient,
    ContractAuthorisationError,
    _contract_owner_address,
)


class ContractOwnerWalletTests(SimpleTestCase):
    @override_settings(
        ARC_BLOCKCHAIN="ARC-TESTNET",
        VEYRA_CONTRACT_ADDRESS="0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5",
        VEYRA_CONTRACT_AUTHORISATION_FEE_LEVEL="MEDIUM",
    )
    def test_circle_contract_call_uses_exact_wallet_id(self):
        client = object.__new__(CircleContractOwnerClient)
        client._sdk = Mock()
        client._transactions = Mock()
        request = object()
        client._sdk.CreateContractExecutionTransactionForDeveloperRequest.from_dict.return_value = request
        client._transactions.create_developer_transaction_contract_execution.return_value = {
            "data": {
                "id": "circle-tx-1",
                "state": "INITIATED",
            }
        }

        result = client.create_authorisation(
            owner_wallet_id="circle-platform-wallet-id",
            agent_address="0x99Bc52a8aa5931A652620e901BF434DeD949348d",
            idempotency_key=uuid.uuid4(),
        )

        payload = (
            client._sdk.CreateContractExecutionTransactionForDeveloperRequest
            .from_dict.call_args.args[0]
        )
        self.assertEqual(payload["walletId"], "circle-platform-wallet-id")
        self.assertNotIn("walletAddress", payload)
        self.assertEqual(
            payload["abiFunctionSignature"],
            "setAgentAuthorised(address,bool)",
        )
        self.assertEqual(result["id"], "circle-tx-1")

    @override_settings(
        VEYRA_CONTRACT_OWNER_WALLET_ADDRESS="0x1111111111111111111111111111111111111111"
    )
    def test_configured_owner_must_match_onchain_owner(self):
        arc = Mock()
        arc.contract.functions.owner.return_value.call.return_value = (
            "0x2222222222222222222222222222222222222222"
        )

        with self.assertRaisesMessage(
            ContractAuthorisationError,
            "does not yet own the Veyra contract",
        ):
            _contract_owner_address(arc)
