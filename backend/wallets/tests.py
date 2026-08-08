from unittest.mock import patch
from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from accounts.models import ClientProfile, PendingCircleAuth, User, UserCapability, VeyraSession
from accounts.services import create_pending_circle_auth
from wallets.services import sync_wallet_for_existing_user
from wallets.models import WalletAccount

@override_settings(CIRCLE_API_KEY='test-key')
class WalletProvisioningTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_token = 'u' * 40
        raw, pending = create_pending_circle_auth(
            user_token=self.user_token,
            circle_user_id='circle-user-1',
            method='GOOGLE',
            email='client@example.com',
            display_name='Client',
        )
        pending.requested_capability = 'CLIENT'
        pending.save(update_fields=['requested_capability'])
        self.pending = pending
        self.client.cookies[settings.VEYRA_ONBOARDING_COOKIE] = raw
        self.client.credentials(HTTP_ORIGIN='http://localhost:3000')

    @patch('wallets.circle.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('wallets.circle.CircleClient.get_wallet', return_value={
        'id': 'wallet-1',
        'address': '0x1111111111111111111111111111111111111111',
        'userId': 'circle-user-1',
    })
    @patch('wallets.views.CircleClient.list_wallets')
    def test_sync_binds_wallet_and_creates_client(self, list_wallets, *_mocks):
        list_wallets.return_value = [{
            'id': 'wallet-1',
            'walletSetId': 'set-1',
            'address': '0x1111111111111111111111111111111111111111',
            'blockchain': 'ARC-TESTNET',
            'accountType': 'SCA',
            'state': 'LIVE',
        }]
        response = self.client.post(
            '/api/v1/client/wallet/sync/',
            {'circle_user_id': 'circle-user-1', 'auth_method': 'GOOGLE'},
            format='json',
            HTTP_X_CIRCLE_USER_TOKEN=self.user_token,
        )
        self.assertEqual(response.status_code, 200)
        wallet = WalletAccount.objects.get()
        self.assertEqual(wallet.account_type, 'SCA')
        self.assertTrue(UserCapability.objects.filter(user=wallet.user, code='CLIENT').exists())
        self.assertIn(settings.VEYRA_SESSION_COOKIE, response.cookies)

    @patch('wallets.views.CircleClient.initialize_user_wallet')
    @patch('wallets.views.CircleClient.list_wallets')
    def test_stale_email_pending_cannot_initialize_circle_wallet(self, list_wallets, initialize_wallet):
        PendingCircleAuth.objects.filter(pk=self.pending.pk).update(auth_method='EMAIL')

        response = self.client.post(
            '/api/v1/client/wallet/initialize/',
            {'circle_user_id': 'email-user', 'auth_method': 'EMAIL'},
            format='json',
            HTTP_X_CIRCLE_USER_TOKEN=self.user_token,
        )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.data['code'], 'email_auth_disabled')
        list_wallets.assert_not_called()
        initialize_wallet.assert_not_called()
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(ClientProfile.objects.count(), 0)
        self.assertEqual(VeyraSession.objects.count(), 0)
        self.assertEqual(WalletAccount.objects.count(), 0)

    @patch('wallets.views.CircleClient.list_wallets')
    def test_stale_email_pending_cannot_sync_or_create_local_rows(self, list_wallets):
        PendingCircleAuth.objects.filter(pk=self.pending.pk).update(auth_method='EMAIL')

        response = self.client.post(
            '/api/v1/client/wallet/sync/',
            {'circle_user_id': 'email-user', 'auth_method': 'EMAIL'},
            format='json',
            HTTP_X_CIRCLE_USER_TOKEN=self.user_token,
        )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.data['code'], 'email_auth_disabled')
        list_wallets.assert_not_called()
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(ClientProfile.objects.count(), 0)
        self.assertEqual(VeyraSession.objects.count(), 0)
        self.assertEqual(WalletAccount.objects.count(), 0)

    def test_existing_arc_wallet_cannot_be_silently_replaced(self):
        user = User.objects.create_user(handle='wallet-owner')
        WalletAccount.objects.create(
            user=user,
            circle_wallet_id='wallet-original',
            wallet_set_id='set-original',
            address='0x2222222222222222222222222222222222222222',
            blockchain='ARC-TESTNET',
            purpose=WalletAccount.Purpose.CLIENT_ESCROW,
        )

        with self.assertRaisesMessage(
            ValidationError,
            'Wallet replacement requires an explicit account-recovery flow.',
        ):
            sync_wallet_for_existing_user(
                user,
                {
                    'id': 'wallet-replacement',
                    'walletSetId': 'set-replacement',
                    'address': '0x3333333333333333333333333333333333333333',
                    'blockchain': 'ARC-TESTNET',
                    'accountType': 'SCA',
                    'state': 'LIVE',
                },
            )

        wallet = WalletAccount.objects.get(user=user, blockchain='ARC-TESTNET')
        self.assertEqual(wallet.circle_wallet_id, 'wallet-original')
        self.assertEqual(
            wallet.address,
            '0x2222222222222222222222222222222222222222',
        )

from datetime import timedelta
from unittest.mock import MagicMock

from django.test import override_settings
from django.utils import timezone
from web3 import Web3

from accounts.models import User
from jobs.models import JobDraft, VeyraJob
from jobs.services import lock_funding_snapshot
from wallets.models import CircleTransaction
from wallets.transaction_sync import sync_transaction


@override_settings(ARC_TRANSACTION_SYNC_MIN_INTERVAL_SECONDS=0)
class TargetedTransactionSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(display_name='Funding Client')
        self.wallet = WalletAccount.objects.create(
            user=self.user,
            circle_wallet_id='wallet-targeted-sync',
            address='0x1111111111111111111111111111111111111111',
            blockchain='ARC-TESTNET',
        )
        self.draft = JobDraft.objects.create(
            client=self.user,
            github_issue_url='https://github.com/o/r/issues/1',
            repository_owner='o',
            repository_name='r',
            target_branch='main',
            issue_number=1,
            issue_title='Implement endpoint',
            issue_body='Implement and test the endpoint.',
            budget_usdc='1.000000',
            deadline=timezone.now() + timedelta(days=1),
            acceptance_criteria=['Existing tests pass'],
            advanced_options={
                'required_commands': ['pytest'],
                'allowed_paths': ['app.py', 'tests/**'],
                'forbidden_paths': ['.github/**'],
            },
        )

    def _transaction(self, *, purpose, contract_address, call_data, metadata):
        return CircleTransaction.objects.create(
            user=self.user,
            wallet=self.wallet,
            draft=self.draft,
            purpose=purpose,
            status=CircleTransaction.Status.PENDING_ONCHAIN,
            circle_transaction_id=f'circle-{purpose.lower()}',
            arc_transaction_hash='0x' + 'ab' * 32,
            contract_address=contract_address.lower(),
            call_data_hash=Web3.to_hex(Web3.keccak(hexstr=call_data)),
            request_metadata=metadata,
        )

    @patch('wallets.transaction_sync.ArcClient')
    def test_approval_confirms_from_known_receipt_and_allowance(self, arc_client_class):
        amount = 1_000_000
        call_data = '0x095ea7b3' + '00' * 64
        tx = self._transaction(
            purpose=CircleTransaction.Purpose.USDC_APPROVAL,
            contract_address=settings.ARC_USDC_ADDRESS,
            call_data=call_data,
            metadata={'draft_id': str(self.draft.id), 'amount_atomic': amount},
        )
        arc = arc_client_class.return_value
        arc.transaction_receipt_or_none.return_value = {
            'status': 1,
            'blockNumber': 101,
            'gasUsed': 45000,
        }
        arc.transaction.return_value = {
            'from': self.wallet.address,
            'to': settings.ARC_USDC_ADDRESS,
            'input': call_data,
        }
        arc.allowance.return_value = amount

        synced = sync_transaction(tx, force=True)

        self.assertEqual(synced.status, CircleTransaction.Status.CONFIRMED)
        self.assertEqual(synced.block_number, 101)
        self.assertEqual(synced.event_payload['allowance_atomic'], amount)
        self.assertFalse(VeyraJob.objects.exists())

    @patch('wallets.transaction_sync.ArcClient')
    def test_job_created_event_creates_local_job_without_indexer(self, arc_client_class):
        snapshot = lock_funding_snapshot(self.draft)
        self.draft.status = JobDraft.Status.FUNDING
        self.draft.save(update_fields=['status', 'updated_at'])
        call_data = '0xbb0a450e' + '00' * 224
        tx = self._transaction(
            purpose=CircleTransaction.Purpose.JOB_CREATE,
            contract_address=settings.VEYRA_CONTRACT_ADDRESS,
            call_data=call_data,
            metadata={
                'draft_id': str(self.draft.id),
                'snapshot_id': str(snapshot.id),
            },
        )
        arc = arc_client_class.return_value
        arc.transaction_receipt_or_none.return_value = {
            'status': 1,
            'blockNumber': 202,
            'gasUsed': 210000,
        }
        arc.transaction.return_value = {
            'from': self.wallet.address,
            'to': settings.VEYRA_CONTRACT_ADDRESS,
            'input': call_data,
        }
        arc.decode_receipt_event.return_value = [{
            'args': {
                'jobId': 7,
                'client': self.wallet.address,
                'verifier': snapshot.verifier_address,
                'invitedProvider': snapshot.invited_provider_address,
                'budget': int(snapshot.budget_atomic),
                'expiresAt': snapshot.expires_at,
                'repositoryHash': bytes.fromhex(snapshot.repository_hash[2:]),
                'taskHash': bytes.fromhex(snapshot.task_hash[2:]),
                'policyHash': bytes.fromhex(snapshot.policy_hash[2:]),
            }
        }]

        synced = sync_transaction(tx, force=True)

        self.assertEqual(synced.status, CircleTransaction.Status.CONFIRMED)
        self.assertEqual(synced.job.onchain_job_id, 7)
        self.assertEqual(VeyraJob.objects.get().client_status, 'OPEN')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, JobDraft.Status.FUNDED)

    @patch('wallets.transaction_sync.ArcClient')
    def test_event_mismatch_does_not_unlock_draft_for_double_funding(self, arc_client_class):
        snapshot = lock_funding_snapshot(self.draft)
        self.draft.status = JobDraft.Status.FUNDING
        self.draft.save(update_fields=['status', 'updated_at'])
        call_data = '0xbb0a450e' + '00' * 224
        tx = self._transaction(
            purpose=CircleTransaction.Purpose.JOB_CREATE,
            contract_address=settings.VEYRA_CONTRACT_ADDRESS,
            call_data=call_data,
            metadata={
                'draft_id': str(self.draft.id),
                'snapshot_id': str(snapshot.id),
            },
        )
        arc = arc_client_class.return_value
        arc.transaction_receipt_or_none.return_value = {
            'status': 1,
            'blockNumber': 303,
            'gasUsed': 210000,
        }
        arc.transaction.return_value = {
            'from': self.wallet.address,
            'to': settings.VEYRA_CONTRACT_ADDRESS,
            'input': call_data,
        }
        arc.decode_receipt_event.return_value = [{
            'args': {
                'jobId': 8,
                'client': self.wallet.address,
                'verifier': snapshot.verifier_address,
                'invitedProvider': snapshot.invited_provider_address,
                'budget': int(snapshot.budget_atomic) + 1,
                'expiresAt': snapshot.expires_at,
                'repositoryHash': bytes.fromhex(snapshot.repository_hash[2:]),
                'taskHash': bytes.fromhex(snapshot.task_hash[2:]),
                'policyHash': bytes.fromhex(snapshot.policy_hash[2:]),
            }
        }]

        synced = sync_transaction(tx, force=True)

        self.assertEqual(synced.status, CircleTransaction.Status.EVENT_MISMATCH)
        self.assertIn('budget', synced.failure_message)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, JobDraft.Status.FUNDING)
        self.assertFalse(VeyraJob.objects.exists())

    @patch('wallets.transaction_sync.CircleClient')
    @patch('wallets.transaction_sync.ArcClient')
    def test_challenge_first_transaction_resolves_by_ref_id(
        self,
        arc_client_class,
        circle_client_class,
    ):
        amount = 1_000_000
        call_data = '0x095ea7b3' + '00' * 64
        tx = CircleTransaction.objects.create(
            user=self.user,
            wallet=self.wallet,
            draft=self.draft,
            purpose=CircleTransaction.Purpose.USDC_APPROVAL,
            status=CircleTransaction.Status.USER_APPROVAL_PENDING,
            circle_challenge_id='challenge-only',
            circle_reference_id='',
            contract_address=settings.ARC_USDC_ADDRESS.lower(),
            call_data_hash=Web3.to_hex(Web3.keccak(hexstr=call_data)),
            request_metadata={
                'draft_id': str(self.draft.id),
                'amount_atomic': amount,
            },
        )

        circle = circle_client_class.return_value
        remote = {
            'id': 'circle-after-approval',
            'refId': str(tx.id),
            'walletId': self.wallet.circle_wallet_id,
            'blockchain': 'ARC-TESTNET',
            'contractAddress': settings.ARC_USDC_ADDRESS,
            'state': 'COMPLETE',
            'txHash': '0x' + 'cd' * 32,
        }
        circle.list_transactions.return_value = [remote]
        circle.get_transaction.return_value = remote

        arc = arc_client_class.return_value
        arc.transaction_receipt_or_none.return_value = {
            'status': 1,
            'blockNumber': 404,
            'gasUsed': 45000,
        }
        arc.transaction.return_value = {
            'from': self.wallet.address,
            'to': settings.ARC_USDC_ADDRESS,
            'input': call_data,
        }
        arc.allowance.return_value = amount

        synced = sync_transaction(tx, user_token='u' * 40, force=True)

        self.assertEqual(
            synced.circle_transaction_id,
            'circle-after-approval',
        )
        self.assertEqual(synced.arc_transaction_hash, '0x' + 'cd' * 32)
        self.assertEqual(synced.status, CircleTransaction.Status.CONFIRMED)


    @patch('wallets.transaction_sync.CircleClient')
    @patch('wallets.transaction_sync.ArcClient')
    def test_challenge_first_transaction_resolves_without_ref_id(
        self,
        arc_client_class,
        circle_client_class,
    ):
        amount = 1_000_000
        call_data = '0x095ea7b3' + '00' * 64
        submitted_at = timezone.now()
        tx = CircleTransaction.objects.create(
            user=self.user,
            wallet=self.wallet,
            draft=self.draft,
            purpose=CircleTransaction.Purpose.USDC_APPROVAL,
            status=CircleTransaction.Status.USER_APPROVAL_PENDING,
            circle_challenge_id='challenge-without-ref',
            circle_reference_id=str(self.draft.id),
            contract_address=settings.ARC_USDC_ADDRESS.lower(),
            call_data_hash=Web3.to_hex(Web3.keccak(hexstr=call_data)),
            request_metadata={
                'draft_id': str(self.draft.id),
                'amount_atomic': amount,
                'memo': f'Approve USDC for Veyra job {self.draft.id}',
            },
            submitted_at=submitted_at,
        )

        circle = circle_client_class.return_value
        remote = {
            'id': 'circle-without-ref-id',
            'refId': '',
            'walletId': self.wallet.circle_wallet_id,
            'sourceAddress': self.wallet.address,
            'blockchain': 'ARC-TESTNET',
            'contractAddress': settings.ARC_USDC_ADDRESS,
            'operation': 'CONTRACT_EXECUTION',
            'memo': f'Approve USDC for Veyra job {self.draft.id}',
            'state': 'COMPLETE',
            'txHash': '0x' + 'ef' * 32,
            'createDate': submitted_at.isoformat(),
        }
        circle.list_transactions.return_value = [remote]
        circle.get_transaction.return_value = remote

        arc = arc_client_class.return_value
        arc.transaction_receipt_or_none.return_value = {
            'status': 1,
            'blockNumber': 505,
            'gasUsed': 45000,
        }
        arc.transaction.return_value = {
            'from': self.wallet.address,
            'to': settings.ARC_USDC_ADDRESS,
            'input': call_data,
        }
        arc.allowance.return_value = amount

        synced = sync_transaction(tx, user_token='u' * 40, force=True)

        circle.list_transactions.assert_called_once_with(
            'u' * 40,
            wallet_id=self.wallet.circle_wallet_id,
        )
        self.assertEqual(
            synced.circle_transaction_id,
            'circle-without-ref-id',
        )
        self.assertEqual(synced.arc_transaction_hash, '0x' + 'ef' * 32)
        self.assertEqual(synced.status, CircleTransaction.Status.CONFIRMED)
