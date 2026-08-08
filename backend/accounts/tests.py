import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from accounts.models import ClientProfile, ExternalIdentity, PendingCircleAuth, User, UserCapability
from accounts.services import issue_session
from common.models import AuditLog
from wallets.models import WalletAccount


ARC_WALLET = {
    'id': 'wallet-1',
    'address': '0x1111111111111111111111111111111111111111',
    'blockchain': 'ARC-TESTNET',
    'accountType': 'SCA',
}


@override_settings(CIRCLE_API_KEY='test-key')
class CircleAuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_ORIGIN=next(iter(settings.VEYRA_ALLOWED_ORIGINS)))

    @patch('accounts.views.CircleClient.list_wallets', return_value=[])
    def test_exchange_creates_provisional_onboarding_not_user(self, _list_wallets):
        response = self.client.post('/api/v1/auth/circle/exchange/', {
            'user_token': 't' * 40,
            'circle_user_id': 'circle-user-1',
            'auth_method': 'GOOGLE',
            'email': 'client@example.com',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['requires_wallet_setup'])
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(PendingCircleAuth.objects.count(), 1)
        self.assertIn(settings.VEYRA_ONBOARDING_COOKIE, response.cookies)

    @patch('wallets.circle.CircleClient.get_user', return_value={'id': 'circle-user-1', 'authMode': 'SSO'})
    @patch('wallets.circle.CircleClient.get_wallet', return_value={
        'id': 'wallet-1', 'address': ARC_WALLET['address'], 'userId': 'circle-user-1',
    })
    @patch('accounts.views.CircleClient.list_wallets', return_value=[ARC_WALLET])
    def test_repeated_google_exchange_is_identity_and_wallet_idempotent(self, *_mocks):
        user = User.objects.create_user(display_name='Client')
        UserCapability.objects.create(user=user, code=UserCapability.Code.CLIENT)
        UserCapability.objects.create(user=user, code=UserCapability.Code.AGENT_OWNER)
        ClientProfile.objects.create(user=user)
        wallet = WalletAccount.objects.create(
            user=user, circle_wallet_id='wallet-1', address=ARC_WALLET['address'],
            blockchain='ARC-TESTNET',
        )
        ExternalIdentity.objects.create(
            user=user, provider=ExternalIdentity.Provider.CIRCLE,
            provider_user_id='wallet:wallet-1', method=ExternalIdentity.Method.GOOGLE,
        )
        for _ in range(2):
            response = self.client.post('/api/v1/auth/circle/exchange/', {
                'user_token': 't' * 40, 'circle_user_id': 'spoofed-value', 'auth_method': 'GOOGLE',
            }, format='json')
            self.assertEqual(response.status_code, 200, response.content.decode())
            self.assertTrue(response.data['authenticated'])

        identity = ExternalIdentity.objects.get()
        self.assertEqual(identity.provider, ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE)
        self.assertEqual(identity.provider_user_id, 'circle-user-1')
        self.assertNotEqual(identity.provider_user_id, f'wallet:{wallet.circle_wallet_id}')
        self.assertEqual(identity.user_id, user.id)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(ClientProfile.objects.count(), 1)
        self.assertEqual(WalletAccount.objects.count(), 1)
        self.assertSetEqual(set(user.capabilities.values_list('code', flat=True)), {'CLIENT', 'AGENT_OWNER'})

    @patch('wallets.circle.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('wallets.circle.CircleClient.get_wallet', return_value={
        'id': 'wallet-2', 'address': '0x2222222222222222222222222222222222222222',
        'userId': 'circle-user-1',
    })
    @patch('accounts.views.CircleClient.list_wallets')
    def test_known_identity_rejects_wallet_mismatch(self, list_wallets, *_mocks):
        user = User.objects.create_user()
        ExternalIdentity.objects.create(
            user=user, provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
            provider_user_id='circle-user-1', method=ExternalIdentity.Method.GOOGLE,
        )
        WalletAccount.objects.create(
            user=user, circle_wallet_id='wallet-1', address=ARC_WALLET['address'], blockchain='ARC-TESTNET',
        )
        list_wallets.return_value = [{**ARC_WALLET, 'id': 'wallet-2', 'address': '0x2222222222222222222222222222222222222222'}]
        response = self.client.post('/api/v1/auth/circle/exchange/', {
            'user_token': 't' * 40, 'circle_user_id': 'circle-user-1', 'auth_method': 'GOOGLE',
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'wallet_mismatch')
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(WalletAccount.objects.count(), 1)

    @patch('wallets.circle.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('wallets.circle.CircleClient.get_wallet', return_value={
        'id': 'wallet-1', 'address': ARC_WALLET['address'], 'userId': 'circle-user-1',
    })
    @patch('accounts.views.CircleClient.list_wallets')
    def test_wallet_order_and_extra_resource_reuse_canonical_wallet(self, list_wallets, *_mocks):
        user = User.objects.create_user()
        ExternalIdentity.objects.create(
            user=user, provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
            provider_user_id='circle-user-1', method=ExternalIdentity.Method.GOOGLE,
        )
        canonical = WalletAccount.objects.create(
            user=user, circle_wallet_id='wallet-1', address=ARC_WALLET['address'], blockchain='ARC-TESTNET',
        )
        extra = {**ARC_WALLET, 'id': 'wallet-2', 'address': '0x2222222222222222222222222222222222222222'}
        list_wallets.return_value = [extra, ARC_WALLET]
        response = self.client.post('/api/v1/auth/circle/exchange/', {
            'user_token': 't' * 40, 'circle_user_id': 'spoofed', 'auth_method': 'GOOGLE',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['wallet']['address'], canonical.address)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(ExternalIdentity.objects.count(), 1)
        self.assertEqual(WalletAccount.objects.count(), 1)


@override_settings(CIRCLE_API_KEY='test-key', VEYRA_EMAIL_AUTH_ENABLED=False)
class EmailAuthDisabledTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def assert_disabled(self, path, payload):
        response = self.client.post(path, payload, format='json')
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.data['code'], 'email_auth_disabled')

    @patch('accounts.views.CircleClient.create_email_token')
    def test_request_verify_and_resend_are_disabled_without_side_effects(self, create_email_token):
        payload = {'device_id': 'device-1', 'email': 'victim@example.com'}
        for path in (
            '/api/v1/auth/circle/email/request/',
            '/api/v1/auth/circle/email/verify/',
            '/api/v1/auth/circle/email/resend/',
        ):
            self.assert_disabled(path, payload)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(ClientProfile.objects.count(), 0)
        self.assertEqual(WalletAccount.objects.count(), 0)
        create_email_token.assert_not_called()

    @patch('accounts.views.CircleClient.list_wallets')
    def test_direct_email_exchange_cannot_link_victim_or_create_rows(self, list_wallets):
        self.assert_disabled('/api/v1/auth/circle/exchange/', {
            'user_token': 't' * 40, 'circle_user_id': 'email-user',
            'auth_method': 'EMAIL', 'email': 'victim@example.com',
        })
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(ClientProfile.objects.count(), 0)
        self.assertEqual(WalletAccount.objects.count(), 0)
        list_wallets.assert_not_called()

class SessionAuthenticationTests(TestCase):
    def test_http_only_session_authenticates_me_with_capabilities(self):
        user = User.objects.create_user(display_name='Client')
        UserCapability.objects.create(user=user, code=UserCapability.Code.CLIENT)
        UserCapability.objects.create(user=user, code=UserCapability.Code.AGENT_OWNER)
        raw, _ = issue_session(user, type('Request', (), {'headers': {}})())
        client = APIClient()
        client.cookies[settings.VEYRA_SESSION_COOKIE] = raw
        response = client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['authenticated'])
        self.assertSetEqual(set(response.data['capabilities']), {'CLIENT', 'AGENT_OWNER'})


@override_settings(CIRCLE_API_KEY='test-key', VEYRA_RECONCILIATION_TESTS_PASSED=True)
class ReconciliationCommandTests(TestCase):
    canonical_id = '7593262e-3352-40bd-b5d9-7bcb21d1a8d6'
    duplicate_id = 'c3b3278a-3bea-47e8-8950-ec49b1ed36d0'

    def setUp(self):
        self.backup = tempfile.NamedTemporaryFile(delete=False)
        self.backup.write(b'valid-backup')
        self.backup.close()
        self.settings_override = override_settings(VEYRA_RECONCILIATION_BACKUP_PATH=self.backup.name)
        self.settings_override.enable()
        self.canonical = User.objects.create_user(id=self.canonical_id)
        self.duplicate = User.objects.create_user(id=self.duplicate_id, email='duplicate@example.com')
        for code in (UserCapability.Code.CLIENT, UserCapability.Code.AGENT_OWNER):
            UserCapability.objects.create(user=self.canonical, code=code)
        UserCapability.objects.create(user=self.duplicate, code=UserCapability.Code.CLIENT)
        ClientProfile.objects.create(user=self.canonical, organisation_name='Canonical')
        ClientProfile.objects.create(user=self.duplicate)
        ExternalIdentity.objects.create(
            user=self.canonical, provider=ExternalIdentity.Provider.CIRCLE_SSO_GOOGLE,
            provider_user_id='0067ba7e-test', method=ExternalIdentity.Method.GOOGLE,
        )
        ExternalIdentity.objects.create(
            user=self.duplicate, provider=ExternalIdentity.Provider.CIRCLE,
            provider_user_id='wallet:duplicate', method=ExternalIdentity.Method.EMAIL,
        )
        WalletAccount.objects.create(
            user=self.canonical, circle_wallet_id='canonical-wallet',
            address='0x68301b0000000000000000000000000000007949', blockchain='ARC-TESTNET',
        )
        WalletAccount.objects.create(
            user=self.duplicate, circle_wallet_id='duplicate-wallet',
            address='0x63cc660000000000000000000000000000004c33', blockchain='ARC-TESTNET',
        )
        AuditLog.objects.create(actor=self.duplicate, action='EMAIL_AUTH')

    def tearDown(self):
        self.settings_override.disable()
        Path(self.backup.name).unlink(missing_ok=True)

    def command(self, mode, **extra):
        from accounts.management.commands.reconcile_google_only_duplicate import Command
        original_counts = Command._related_counts

        def counts_with_known_history(user):
            counts = original_counts(user)
            if str(user.pk) == self.canonical_id:
                counts.update({'jobs': 7, 'drafts': 12, 'agents': 4, 'transactions': 21})
            return counts

        with patch.object(Command, '_related_counts', side_effect=counts_with_known_history):
            call_command(
                'reconcile_google_only_duplicate', mode,
                canonical_user_id=self.canonical_id, duplicate_user_id=self.duplicate_id, **extra,
            )

    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_wallet', return_value={
        'id': 'canonical-wallet', 'address': '0x68301b0000000000000000000000000000007949',
        'userId': '0067ba7e-test',
    })
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.wallet_balances_for_wallet', return_value=[])
    def test_dry_run_changes_nothing_and_wrong_confirmation_fails(self, *_mocks):
        self.command('--dry-run')
        self.assertTrue(User.objects.filter(pk=self.duplicate_id).exists())
        with self.assertRaises(CommandError):
            self.command('--apply', confirm='wrong')

    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_wallet', return_value={
        'id': 'canonical-wallet', 'address': '0x68301b0000000000000000000000000000007949',
        'userId': '0067ba7e-test',
    })
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.wallet_balances_for_wallet', return_value=[{'amount': '1', 'token': {'symbol': 'USDC'}}])
    def test_non_zero_live_balance_blocks_deletion(self, *_mocks):
        with self.assertRaises(CommandError):
            self.command('--dry-run')
        self.assertTrue(User.objects.filter(pk=self.duplicate_id).exists())

    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_wallet', return_value={
        'id': 'canonical-wallet', 'address': '0x68301b0000000000000000000000000000007949',
        'userId': '0067ba7e-test',
    })
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.wallet_balances_for_wallet', return_value=[])
    def test_apply_removes_only_local_duplicate_and_preserves_audit_and_canonical(self, *_mocks):
        self.command('--apply', confirm=f'DELETE-EMPTY-DUPLICATE-{self.duplicate_id}')
        self.assertFalse(User.objects.filter(pk=self.duplicate_id).exists())
        self.assertTrue(User.objects.filter(pk=self.canonical_id).exists())
        self.assertEqual(WalletAccount.objects.filter(user_id=self.canonical_id).count(), 1)
        event = AuditLog.objects.get()
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.metadata['removed_local_duplicate_user_id'], self.duplicate_id)

    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_wallet', return_value={
        'id': 'canonical-wallet', 'address': '0x68301b0000000000000000000000000000007949',
        'userId': '0067ba7e-test',
    })
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.wallet_balances_for_wallet', return_value=[])
    def test_login_email_and_timezone_only_are_disposable_bootstrap_metadata(self, *_mocks):
        profile = self.duplicate.client_profile
        profile.notification_email = self.duplicate.email
        profile.timezone = 'Africa/Lagos'
        profile.save(update_fields=['notification_email', 'timezone'])

        self.command('--dry-run')
        self.assertTrue(User.objects.filter(pk=self.duplicate_id).exists())

    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_wallet', return_value={
        'id': 'canonical-wallet', 'address': '0x68301b0000000000000000000000000000007949',
        'userId': '0067ba7e-test',
    })
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.wallet_balances_for_wallet', return_value=[])
    def test_custom_profile_data_blocks_deletion(self, *_mocks):
        profile = self.duplicate.client_profile
        profile.notification_email = 'other-contact@example.com'
        profile.save(update_fields=['notification_email'])

        with self.assertRaises(CommandError):
            self.command('--dry-run')
        self.assertTrue(User.objects.filter(pk=self.duplicate_id).exists())

    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_wallet', return_value={
        'id': 'canonical-wallet', 'address': '0x68301b0000000000000000000000000000007949',
        'userId': '0067ba7e-test',
    })
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.wallet_balances_for_wallet', return_value=[])
    def test_post_cleanup_dry_run_revalidates_canonical_account(self, *_mocks):
        self.command('--apply', confirm=f'DELETE-EMPTY-DUPLICATE-{self.duplicate_id}')

        self.command('--dry-run')

        self.assertFalse(User.objects.filter(pk=self.duplicate_id).exists())
        self.assertTrue(User.objects.filter(pk=self.canonical_id).exists())
        self.assertEqual(WalletAccount.objects.filter(user_id=self.canonical_id).count(), 1)

    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_user', return_value={'authMode': 'SSO'})
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.get_wallet', return_value={
        'id': 'canonical-wallet', 'address': '0x68301b0000000000000000000000000000007949',
        'userId': '0067ba7e-test',
    })
    @patch('accounts.management.commands.reconcile_google_only_duplicate.CircleClient.wallet_balances_for_wallet', return_value=[])
    def test_post_cleanup_dry_run_blocks_if_canonical_wallet_changes(self, *_mocks):
        self.command('--apply', confirm=f'DELETE-EMPTY-DUPLICATE-{self.duplicate_id}')
        wallet = WalletAccount.objects.get(user_id=self.canonical_id)
        wallet.address = '0x9999999999999999999999999999999999999999'
        wallet.save(update_fields=['address'])

        with self.assertRaises(CommandError):
            self.command('--dry-run')
