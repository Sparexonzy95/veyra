from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User, UserCapability
from workers.models import AgentWithdrawal, WorkerAgent, WorkerReputationSnapshot
from workers.withdrawals import (
    AgentWithdrawalError,
    create_withdrawal,
    reconcile_withdrawal,
    wallet_snapshot,
)


@override_settings(
    ARC_BLOCKCHAIN="ARC-TESTNET",
    ARC_USDC_ADDRESS="0x3600000000000000000000000000000000000000",
    ARC_USDC_DECIMALS=6,
    CIRCLE_API_KEY="test-key",
    CIRCLE_ENTITY_SECRET="test-secret",
)
class AgentWithdrawalTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(handle="withdraw-owner")
        UserCapability.objects.create(user=self.owner, code=UserCapability.Code.AGENT_OWNER)
        self.other = User.objects.create_user(handle="other-withdraw-owner")
        UserCapability.objects.create(user=self.other, code=UserCapability.Code.AGENT_OWNER)
        self.worker = WorkerAgent.objects.create(
            slug="withdraw-agent",
            name="Withdraw Agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
            languages=["Python"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="test-runtime",
            circle_wallet_id="circle-worker-wallet",
            circle_wallet_set_id="circle-worker-wallet-set",
            worker_wallet_address="0x2222222222222222222222222222222222222222",
            payout_wallet_address="0x2222222222222222222222222222222222222222",
        )
        WorkerReputationSnapshot.objects.create(
            worker=self.worker,
            total_earned_atomic=3_000_000,
            completed_jobs=3,
        )

    @patch("workers.withdrawals.read_worker_usdc_balance", return_value=Decimal("2.500000"))
    def test_available_is_capped_by_live_balance_minus_operational_reserve(self, _balance):
        snapshot = wallet_snapshot(self.worker, self.owner, reconcile=False)
        self.assertEqual(snapshot["lifetime_earned_usdc"], "3.000000")
        self.assertEqual(snapshot["live_balance_usdc"], "2.500000")
        self.assertEqual(snapshot["operational_reserve_usdc"], "0.050000")
        self.assertEqual(snapshot["available_to_withdraw_usdc"], "2.450000")

    @patch("workers.withdrawals.read_worker_usdc_balance", return_value=Decimal("5.000000"))
    def test_completed_withdrawal_reduces_earned_amount_available(self, _balance):
        AgentWithdrawal.objects.create(
            worker=self.worker,
            owner_user=self.owner,
            destination_address="0x3333333333333333333333333333333333333333",
            amount_usdc="1.250000",
            status=AgentWithdrawal.Status.COMPLETED,
        )
        snapshot = wallet_snapshot(self.worker, self.owner, reconcile=False)
        self.assertEqual(snapshot["withdrawn_usdc"], "1.250000")
        self.assertEqual(snapshot["available_to_withdraw_usdc"], "1.750000")

    @patch("workers.withdrawals.read_worker_usdc_balance", return_value=Decimal("3.000000"))
    @patch("workers.withdrawals._init_circle")
    def test_duplicate_click_reuses_pending_withdrawal_and_creates_one_circle_transfer(self, init_circle, _balance):
        transactions_api = Mock()
        transactions_api.create_developer_transaction_transfer.return_value = {
            "data": {"id": "circle-tx-1", "state": "INITIATED"}
        }
        developer = SimpleNamespace(
            TransactionsApi=lambda _client: transactions_api,
            CreateTransferTransactionForDeveloperRequest=SimpleNamespace(from_dict=lambda value: value),
        )
        init_circle.return_value = (developer, object())

        first = create_withdrawal(
            worker=self.worker,
            owner=self.owner,
            destination_address="0x3333333333333333333333333333333333333333",
            amount_usdc="1.000000",
        )
        second = create_withdrawal(
            worker=self.worker,
            owner=self.owner,
            destination_address="0x3333333333333333333333333333333333333333",
            amount_usdc="1.000000",
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(AgentWithdrawal.objects.count(), 1)
        self.assertEqual(transactions_api.create_developer_transaction_transfer.call_count, 1)
        self.assertEqual(first.status, AgentWithdrawal.Status.PENDING)


    @patch("workers.withdrawals._init_circle")
    def test_pending_circle_transaction_completes_from_confirmed_arc_receipt(self, init_circle):
        withdrawal = AgentWithdrawal.objects.create(
            worker=self.worker,
            owner_user=self.owner,
            destination_address="0x3333333333333333333333333333333333333333",
            amount_usdc="0.250000",
            status=AgentWithdrawal.Status.PENDING,
            circle_transaction_id="circle-tx-pending",
        )
        transactions_api = Mock()
        transactions_api.get_transaction.return_value = {
            "data": {
                "transaction": {
                    "id": "circle-tx-pending",
                    "state": "PENDING",
                    "txHash": "0x" + "12" * 32,
                }
            }
        }
        developer = SimpleNamespace(TransactionsApi=lambda _client: transactions_api)
        init_circle.return_value = (developer, object())
        arc = Mock()
        arc.transaction_receipt_or_none.return_value = {"status": 1}

        refreshed = reconcile_withdrawal(withdrawal, arc_client=arc)

        self.assertEqual(refreshed.status, AgentWithdrawal.Status.COMPLETED)
        self.assertTrue(refreshed.completed_at)
        self.assertEqual(refreshed.arc_transaction_hash, "0x" + "12" * 32)

    @patch("workers.withdrawals._init_circle")
    def test_pending_circle_transaction_fails_from_reverted_arc_receipt(self, init_circle):
        withdrawal = AgentWithdrawal.objects.create(
            worker=self.worker,
            owner_user=self.owner,
            destination_address="0x3333333333333333333333333333333333333333",
            amount_usdc="0.250000",
            status=AgentWithdrawal.Status.PENDING,
            circle_transaction_id="circle-tx-reverted",
        )
        transactions_api = Mock()
        transactions_api.get_transaction.return_value = {
            "data": {
                "transaction": {
                    "id": "circle-tx-reverted",
                    "state": "PENDING",
                    "txHash": "0x" + "34" * 32,
                }
            }
        }
        developer = SimpleNamespace(TransactionsApi=lambda _client: transactions_api)
        init_circle.return_value = (developer, object())
        arc = Mock()
        arc.transaction_receipt_or_none.return_value = {"status": 0}

        refreshed = reconcile_withdrawal(withdrawal, arc_client=arc)

        self.assertEqual(refreshed.status, AgentWithdrawal.Status.FAILED)
        self.assertIn("reverted", refreshed.failure_message.lower())

    @patch("workers.withdrawals.read_worker_usdc_balance", return_value=Decimal("0.500000"))
    def test_withdrawal_cannot_exceed_available_earnings(self, _balance):
        with self.assertRaisesMessage(AgentWithdrawalError, "Only 0.450000 USDC"):
            create_withdrawal(
                worker=self.worker,
                owner=self.owner,
                destination_address="0x3333333333333333333333333333333333333333",
                amount_usdc="1.000000",
            )

    def test_owner_api_cannot_access_another_owners_withdrawal_routes(self):
        client = APIClient()
        client.force_authenticate(self.other)
        response = client.get(f"/api/v1/agents/{self.worker.id}/wallet/")
        self.assertEqual(response.status_code, 404)
