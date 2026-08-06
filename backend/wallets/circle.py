import uuid

import httpx
from django.conf import settings


class CircleError(RuntimeError):
    def __init__(self, message, *, status_code=None, code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.payload = payload or {}


class CircleClient:
    def __init__(self):
        if not settings.CIRCLE_API_KEY:
            raise CircleError('CIRCLE_API_KEY is not configured.')
        self.base_url = settings.CIRCLE_BASE_URL.rstrip('/')
        self.timeout = settings.CIRCLE_TIMEOUT_SECONDS

    def _headers(self, user_token=None):
        headers = {
            'Authorization': f'Bearer {settings.CIRCLE_API_KEY}',
            'Content-Type': 'application/json',
        }
        if user_token:
            headers['X-User-Token'] = user_token
        return headers

    def _request(self, method, path, *, user_token=None, json=None, params=None):
        try:
            response = httpx.request(
                method,
                f'{self.base_url}{path}',
                headers=self._headers(user_token),
                json=json,
                params=params,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise CircleError('Circle request failed.') from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.is_error:
            error = payload.get('error') or payload
            code = error.get('code') if isinstance(error, dict) else None
            message = error.get('message') if isinstance(error, dict) else 'Circle request failed.'
            raise CircleError(
                message or 'Circle request failed.',
                status_code=response.status_code,
                code=code,
                payload=payload,
            )

        return payload.get('data', payload)

    def create_social_device_token(self, device_id):
        return self._request('POST', '/v1/w3s/users/social/token', json={
            'idempotencyKey': str(uuid.uuid4()),
            'deviceId': device_id,
        })

    def create_email_token(self, device_id, email):
        return self._request('POST', '/v1/w3s/users/email/token', json={
            'idempotencyKey': str(uuid.uuid4()),
            'deviceId': device_id,
            'email': email,
        })

    def list_wallets(self, user_token):
        data = self._request('GET', '/v1/w3s/wallets', user_token=user_token)
        return data.get('wallets', []) if isinstance(data, dict) else []

    def get_wallet(self, wallet_id):
        """Read one wallet resource with developer (API key) authority.

        The response carries `userId`: the Circle end user that owns the wallet.
        Reading it here, rather than trusting the browser-supplied SDK `userId`,
        is what makes the human identity server-verified.
        """
        data = self._request('GET', f'/v1/w3s/wallets/{wallet_id}')
        return data.get('wallet', data) if isinstance(data, dict) else {}

    def get_user(self, circle_user_id):
        """Read one Circle end user, including its immutable `authMode`."""
        data = self._request('GET', f'/v1/w3s/users/{circle_user_id}')
        return data.get('user', data) if isinstance(data, dict) else {}


    def initialize_user_wallet(self, user_token):
        return self._request('POST', '/v1/w3s/user/initialize', user_token=user_token, json={
            'idempotencyKey': str(uuid.uuid4()),
            'accountType': 'SCA',
            'blockchains': [settings.ARC_BLOCKCHAIN],
        })

    def wallet_balances(self, user_token, wallet_id):
        data = self._request(
            'GET',
            f'/v1/w3s/wallets/{wallet_id}/balances',
            user_token=user_token,
        )
        return data.get('tokenBalances', data.get('balances', [])) if isinstance(data, dict) else []

    def wallet_balances_for_wallet(self, wallet_id):
        """Read balances with developer authority for reconciliation checks."""
        data = self._request('GET', f'/v1/w3s/wallets/{wallet_id}/balances')
        return data.get('tokenBalances', data.get('balances', [])) if isinstance(data, dict) else []

    def create_contract_execution(self, user_token, payload):
        return self._request(
            'POST',
            '/v1/w3s/user/transactions/contractExecution',
            user_token=user_token,
            json=payload,
        )

    def list_transactions(self, user_token, wallet_id=None):
        """List transactions visible to the authenticated user-controlled wallet session."""
        params = {'pageSize': 50}
        if wallet_id:
            params['walletIds'] = wallet_id

        try:
            data = self._request(
                'GET',
                '/v1/w3s/transactions',
                user_token=user_token,
                params=params,
            )
        except CircleError as exc:
            # Some Circle environments do not accept walletIds/pageSize on the
            # user-controlled list endpoint. Fall back to the unfiltered call.
            if exc.status_code != 400:
                raise
            data = self._request(
                'GET',
                '/v1/w3s/transactions',
                user_token=user_token,
            )

        if isinstance(data, dict):
            transactions = (
                data.get('transactions')
                or data.get('items')
                or data.get('results')
            )
            if isinstance(transactions, list):
                return transactions
            transaction = data.get('transaction')
            if isinstance(transaction, dict):
                return [transaction]
        if isinstance(data, list):
            return data
        return []

    def get_transaction(self, user_token, transaction_id):
        data = self._request(
            'GET',
            f'/v1/w3s/transactions/{transaction_id}',
            user_token=user_token,
        )
        return data.get('transaction', data) if isinstance(data, dict) else data