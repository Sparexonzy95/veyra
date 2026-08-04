from unittest.mock import patch
from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from accounts.models import PendingCircleAuth, User, UserCapability
from accounts.services import issue_session
from common.utils import digest_token
from wallets.models import WalletAccount

@override_settings(CIRCLE_API_KEY='test-key')
class CircleAuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('accounts.views.CircleClient.list_wallets', return_value=[])
    def test_exchange_creates_provisional_onboarding_not_user(self, list_wallets):
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

    @patch('accounts.views.CircleClient.list_wallets')
    def test_returning_wallet_issues_real_session(self, list_wallets):
        user = User.objects.create_user(display_name='Client')
        WalletAccount.objects.create(
            user=user,
            circle_wallet_id='wallet-1',
            address='0x1111111111111111111111111111111111111111',
            blockchain='ARC-TESTNET',
        )
        list_wallets.return_value = [{
            'id': 'wallet-1',
            'address': '0x1111111111111111111111111111111111111111',
            'blockchain': 'ARC-TESTNET',
            'accountType': 'SCA',
        }]
        response = self.client.post('/api/v1/auth/circle/exchange/', {
            'user_token': 't' * 40,
            'circle_user_id': 'circle-user-1',
            'auth_method': 'GOOGLE',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['authenticated'])
        self.assertIn(settings.VEYRA_SESSION_COOKIE, response.cookies)

class SessionAuthenticationTests(TestCase):
    def test_http_only_session_authenticates_me(self):
        user = User.objects.create_user(display_name='Client')
        raw, _ = issue_session(user, type('Request', (), {'headers': {}})())
        client = APIClient()
        client.cookies[settings.VEYRA_SESSION_COOKIE] = raw
        response = client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['authenticated'])
