from django.conf import settings
from drf_spectacular.utils import OpenApiTypes, extend_schema
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.services import CircleIdentityError, bind_google_identity_and_wallet, get_pending_from_request, issue_session, resolve_google_wallet, set_session_cookie
from common.models import AuditLog
from common.permissions import HasClientCapability
from wallets.circle import CircleClient, CircleError
from wallets.models import WalletAccount
from wallets.serializers import WalletInitializeSerializer
from wallets.services import (
    ensure_pending_token_matches, ensure_wallet_owned_by_circle_session, extract_circle_user_token,
    extract_usdc_balance, select_arc_wallet, sync_wallet_for_existing_user,
)


def email_auth_disabled_response():
    return Response(
        {
            'detail': 'Email sign-in is not available. Continue with Google.',
            'code': 'email_auth_disabled',
        },
        status=410,
    )


def reject_non_google_pending(pending):
    if pending and pending.auth_method != 'GOOGLE':
        return email_auth_disabled_response()
    return None


class WalletInitializeView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=WalletInitializeSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = WalletInitializeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_token = extract_circle_user_token(request)
        pending = None
        if not (request.user and request.user.is_authenticated):
            pending = get_pending_from_request(request, user_token=user_token)
            ensure_pending_token_matches(pending, user_token)
            disabled = reject_non_google_pending(pending)
            if disabled:
                return disabled

        circle = CircleClient()
        wallets = circle.list_wallets(user_token)
        if select_arc_wallet(wallets):
            return Response({'wallet_exists': True, 'requires_sync': True})
        try:
            data = circle.initialize_user_wallet(user_token)
        except CircleError as exc:
            if str(exc.code) == '155106':
                return Response({'wallet_exists': True, 'requires_sync': True})
            raise ValidationError(str(exc)) from exc
        challenge_id = data.get('challengeId')
        if not challenge_id:
            raise ValidationError('Circle did not return a wallet creation challenge.')
        return Response({'wallet_exists': False, 'challenge_id': challenge_id, 'account_type': 'SCA', 'blockchain': settings.ARC_BLOCKCHAIN})

class WalletSyncView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=WalletInitializeSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = WalletInitializeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user_token = extract_circle_user_token(request)

        pending = None
        authenticated = request.user and request.user.is_authenticated
        if not authenticated:
            pending = get_pending_from_request(request, user_token=user_token)
            ensure_pending_token_matches(pending, user_token)
            disabled = reject_non_google_pending(pending)
            if disabled:
                return disabled

        circle_wallets = CircleClient().list_wallets(user_token)
        circle_wallet = select_arc_wallet(circle_wallets)
        if not circle_wallet:
            raise NotFound('Arc wallet is not available yet. Complete the Circle challenge and retry.')

        if authenticated:
            wallet = sync_wallet_for_existing_user(request.user, circle_wallet)
            user = request.user
        else:
            try:
                circle_sso_user_id, circle_wallet = resolve_google_wallet(circle_wallets)
                user, wallet = bind_google_identity_and_wallet(
                    wallet=circle_wallet,
                    circle_sso_user_id=circle_sso_user_id,
                    pending=pending,
                    email=data.get('email', ''),
                    display_name=data.get('display_name', ''),
                )
            except CircleIdentityError as exc:
                return Response({'detail': str(exc), 'code': exc.code}, status=exc.status_code)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        raw, _ = issue_session(user, request)
        response = Response({'synced': True, 'wallet': {'address': wallet.address, 'blockchain': wallet.blockchain, 'account_type': wallet.account_type}})
        set_session_cookie(response, raw)
        response.delete_cookie(settings.VEYRA_ONBOARDING_COOKIE, path='/')
        return response

class WalletDetailView(APIView):
    permission_classes = [HasClientCapability]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        wallet = request.user.wallet_accounts.filter(
            blockchain=settings.ARC_BLOCKCHAIN,
            purpose=WalletAccount.Purpose.CLIENT_ESCROW,
        ).first()
        if not wallet:
            raise NotFound('Arc wallet has not been prepared.')
        return Response({
            'id': wallet.id,
            'address': wallet.address,
            'blockchain': wallet.blockchain,
            'account_type': wallet.account_type,
            'status': wallet.status,
            'usdc_balance': str(wallet.last_usdc_balance),
            'last_balance_sync_at': wallet.last_balance_sync_at,
        })

class WalletBalanceView(APIView):
    permission_classes = [HasClientCapability]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        wallet = request.user.wallet_accounts.filter(
            blockchain=settings.ARC_BLOCKCHAIN,
            purpose=WalletAccount.Purpose.CLIENT_ESCROW,
        ).first()
        if not wallet:
            raise NotFound('Arc wallet has not been prepared.')
        user_token = extract_circle_user_token(request)
        circle = CircleClient()
        circle_wallets = circle.list_wallets(user_token)
        ensure_wallet_owned_by_circle_session(circle_wallets, wallet)
        balance = extract_usdc_balance(circle.wallet_balances(user_token, wallet.circle_wallet_id))
        WalletAccount.objects.filter(pk=wallet.pk).update(last_usdc_balance=balance, last_balance_sync_at=timezone.now())
        return Response({'symbol': 'USDC', 'balance': str(balance), 'blockchain': wallet.blockchain})
