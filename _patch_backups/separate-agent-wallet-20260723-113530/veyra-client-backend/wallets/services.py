from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from accounts.services import bind_identity_and_wallet_user
from common.utils import digest_token
from wallets.models import WalletAccount


def select_arc_wallet(wallets):
    matches = [wallet for wallet in wallets if wallet.get('blockchain') == settings.ARC_BLOCKCHAIN]
    if not matches:
        return None
    sca = [wallet for wallet in matches if wallet.get('accountType') == 'SCA']
    return (sca or matches)[0]


def extract_circle_user_token(request):
    token = request.headers.get('X-Circle-User-Token', '')
    if not token:
        raise AuthenticationFailed('X-Circle-User-Token is required for wallet actions.')
    return token


def ensure_pending_token_matches(pending, user_token):
    if not pending or pending.circle_user_token_hash != digest_token(user_token):
        raise AuthenticationFailed('Circle onboarding session does not match this wallet session.')


def ensure_wallet_owned_by_circle_session(circle_wallets, wallet: WalletAccount):
    for candidate in circle_wallets:
        if candidate.get('id') == wallet.circle_wallet_id and candidate.get('address', '').lower() == wallet.address.lower():
            return candidate
    raise AuthenticationFailed('Circle session does not control the wallet linked to this Veyra account.')


@transaction.atomic
def sync_wallet_for_existing_user(user, wallet_data):
    conflict = WalletAccount.objects.filter(circle_wallet_id=wallet_data['id']).exclude(user=user).first()
    if conflict:
        raise ValidationError('Circle wallet is already linked to another Veyra account.')
    address_conflict = WalletAccount.objects.filter(
        blockchain=wallet_data['blockchain'], address__iexact=wallet_data['address']
    ).exclude(user=user).first()
    if address_conflict:
        raise ValidationError('Wallet address is already linked to another Veyra account.')
    has_client_workspace = user.capabilities.filter(
        code='CLIENT',
        revoked_at__isnull=True,
    ).exists()
    wallet, _ = WalletAccount.objects.update_or_create(
        user=user,
        blockchain=wallet_data['blockchain'],
        defaults={
            'circle_wallet_id': wallet_data['id'],
            'wallet_set_id': wallet_data.get('walletSetId', '') or '',
            'address': wallet_data['address'].lower(),
            'account_type': wallet_data.get('accountType', 'SCA'),
            'purpose': (
                WalletAccount.Purpose.CLIENT_ESCROW
                if has_client_workspace
                else WalletAccount.Purpose.IDENTITY_ONLY
            ),
            'status': wallet_data.get('state', 'LIVE'),
        },
    )
    return wallet


def extract_usdc_balance(balances):
    expected = settings.ARC_USDC_ADDRESS.lower()
    for item in balances:
        token = item.get('token', {}) if isinstance(item, dict) else {}
        address = (token.get('tokenAddress') or token.get('address') or '').lower()
        if address == expected:
            return Decimal(str(item.get('amount', '0')))
    for item in balances:
        token = item.get('token', {}) if isinstance(item, dict) else {}
        if token.get('symbol') == 'USDC':
            return Decimal(str(item.get('amount', '0')))
    return Decimal('0')
