import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiTypes, extend_schema
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from common.models import AuditLog
from accounts.models import ClientProfile, PendingCircleAuth, UserCapability, VeyraSession
from accounts.serializers import AgentOwnerOnboardingSerializer, CircleExchangeSerializer, ClientOnboardingSerializer, EmailRequestSerializer, SocialDeviceSerializer
from accounts.services import (
    CircleIdentityError, bind_google_identity_and_wallet, clear_auth_cookies, create_pending_circle_auth, get_pending_from_request,
    grant_agent_owner, grant_client, issue_session, set_onboarding_cookie, set_session_cookie,
    resolve_google_wallet,
)
from wallets.circle import CircleClient, CircleError
from wallets.models import WalletAccount

logger = logging.getLogger(__name__)


def email_auth_disabled_response():
    return Response(
        {'detail': 'Email sign-in is not available. Continue with Google.', 'code': 'email_auth_disabled'},
        status=status.HTTP_410_GONE,
    )


def circle_login_failure(exc, *, operation):
    """
    Translate a CircleError raised during a pre-authentication login step into a
    safe, structured DRF response.

    These endpoints are unauthenticated, so the response must never carry
    Circle's raw message: it can describe our own account configuration (for
    example a missing SMTP setup in the Circle console), which is operator
    diagnostics rather than something a signed-out visitor should read. The
    full detail is logged server-side instead.

    Circle's own 4xx for a rejected address is surfaced as a 400 so the client
    can correct the input. Everything else is an upstream problem and becomes a
    502, because the previous behaviour, letting CircleError escape as an
    unhandled RuntimeError, returned an empty HTTP 500 that told neither the
    user nor the operator anything.
    """
    circle_status = getattr(exc, 'status_code', None)
    circle_code = getattr(exc, 'code', None)
    logger.error(
        'Circle %s failed: status=%s code=%s message=%s',
        operation,
        circle_status,
        circle_code,
        str(exc),
    )

    if circle_status == 400:
        return Response(
            {
                'detail': 'That email address was rejected. Please check it and try again.',
                'code': 'circle_rejected_email',
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            'detail': 'The verification service is temporarily unavailable. Please try again shortly, or continue with Google.',
            'code': 'circle_unavailable',
        },
        status=status.HTTP_502_BAD_GATEWAY,
    )


class CircleSocialDeviceView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=SocialDeviceSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = SocialDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = CircleClient().create_social_device_token(serializer.validated_data['device_id'])
        except CircleError as exc:
            return circle_login_failure(exc, operation='social device token')
        return Response(payload)

class CircleEmailRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=EmailRequestSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        if not settings.VEYRA_EMAIL_AUTH_ENABLED:
            return email_auth_disabled_response()
        serializer = EmailRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payload = CircleClient().create_email_token(data['device_id'], data['email'])
        except CircleError as exc:
            return circle_login_failure(exc, operation='email token')
        return Response(payload)


class CircleEmailDisabledView(APIView):
    """Compatibility tombstone for retired email verify/resend endpoints."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        return email_auth_disabled_response()

class CircleExchangeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=CircleExchangeSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = CircleExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data['auth_method'] != 'GOOGLE':
            return email_auth_disabled_response()
        circle = CircleClient()
        try:
            wallets = circle.list_wallets(data['user_token'])
        except CircleError as exc:
            raise AuthenticationFailed('Circle session could not be validated.') from exc

        try:
            circle_sso_user_id, arc_wallet = resolve_google_wallet(wallets)
        except CircleIdentityError as exc:
            return Response({'detail': str(exc), 'code': exc.code}, status=exc.status_code)
        if arc_wallet:
            try:
                user, wallet = bind_google_identity_and_wallet(
                    wallet=arc_wallet,
                    circle_sso_user_id=circle_sso_user_id,
                    pending=None,
                    email=data.get('email', ''),
                    display_name=data.get('display_name', ''),
                )
            except CircleIdentityError as exc:
                return Response({'detail': str(exc), 'code': exc.code}, status=exc.status_code)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            raw, _ = issue_session(user, request)
            response = Response({'authenticated': True, 'requires_wallet_setup': False, 'wallet': {'address': wallet.address, 'blockchain': wallet.blockchain}})
            set_session_cookie(response, raw)
            return response

        raw, pending = create_pending_circle_auth(
            user_token=data['user_token'],
            circle_user_id=data.get('circle_user_id', ''),
            method=data['auth_method'],
            email=data.get('email', ''),
            display_name=data.get('display_name', ''),
        )
        response = Response({'authenticated': False, 'requires_wallet_setup': True, 'onboarding_id': str(pending.id)})
        set_onboarding_cookie(response, raw)
        return response

class MeView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        if request.user and request.user.is_authenticated:
            capabilities = list(request.user.capabilities.filter(revoked_at__isnull=True).values_list('code', flat=True))
            wallet = None
            if UserCapability.Code.CLIENT in capabilities:
                wallet = request.user.wallet_accounts.filter(
                    blockchain=settings.ARC_BLOCKCHAIN,
                    purpose=WalletAccount.Purpose.CLIENT_ESCROW,
                ).first()
            return Response({
                'authenticated': True,
                'user': {'id': request.user.id, 'display_name': request.user.display_name, 'email': request.user.email},
                'capabilities': capabilities,
                'wallet': {
                    'address': wallet.address,
                    'blockchain': wallet.blockchain,
                    'usdc_balance': str(wallet.last_usdc_balance),
                    'last_balance_sync_at': wallet.last_balance_sync_at,
                } if wallet else None,
            })
        pending = get_pending_from_request(request)
        return Response({'authenticated': False, 'onboarding': bool(pending), 'requires_wallet_setup': bool(pending)})

class LogoutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        if getattr(request, 'veyra_session', None):
            VeyraSession.objects.filter(pk=request.veyra_session.pk).update(revoked_at=timezone.now())
        response = Response(status=204)
        clear_auth_cookies(response)
        return response

class ClientOnboardingView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=ClientOnboardingSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = ClientOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if request.user and request.user.is_authenticated:
            grant_client(request.user)
            profile = request.user.client_profile
            for field, value in data.items():
                setattr(profile, field, value)
            profile.save()
            AuditLog.objects.create(actor=request.user, action='CLIENT_CAPABILITY_GRANTED')
            return Response({
                'capability': 'CLIENT',
                'wallet_setup_required': not request.user.wallet_accounts.filter(
                    blockchain=settings.ARC_BLOCKCHAIN,
                    purpose=WalletAccount.Purpose.CLIENT_ESCROW,
                ).exists(),
            })

        pending = get_pending_from_request(request)
        if not pending:
            raise AuthenticationFailed('Complete Circle sign-in first.')
        pending.requested_capability = UserCapability.Code.CLIENT
        pending.profile_data = data
        if data.get('notification_email'):
            pending.email_hint = data['notification_email']
        pending.save(update_fields=['requested_capability', 'profile_data', 'email_hint'])
        return Response({'capability': 'CLIENT', 'wallet_setup_required': True})


class AgentOwnerOnboardingView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=AgentOwnerOnboardingSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = AgentOwnerOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if request.user and request.user.is_authenticated:
            grant_agent_owner(request.user, serializer.validated_data)
            AuditLog.objects.create(
                actor=request.user,
                action='AGENT_OWNER_CAPABILITY_GRANTED',
            )
            return Response({
                'capability': UserCapability.Code.AGENT_OWNER,
                'wallet_setup_required': False,
                'agent_wallet_policy': 'PER_AGENT_DEVELOPER_CONTROLLED',
            })

        pending = get_pending_from_request(request)
        if not pending:
            raise AuthenticationFailed('Complete Circle sign-in first.')
        pending.requested_capability = UserCapability.Code.AGENT_OWNER
        pending.profile_data = serializer.validated_data
        if serializer.validated_data.get('notification_email'):
            pending.email_hint = serializer.validated_data['notification_email']
        pending.save(update_fields=[
            'requested_capability',
            'profile_data',
            'email_hint',
        ])
        return Response({
            'capability': UserCapability.Code.AGENT_OWNER,
            # The current Circle authentication path still needs a wallet to
            # finish first-time account sign-in. It is stored as IDENTITY_ONLY
            # and is never reused as an agent operational wallet.
            'wallet_setup_required': True,
            'wallet_setup_reason': 'SIGN_IN_IDENTITY',
            'agent_wallet_policy': 'PER_AGENT_DEVELOPER_CONTROLLED',
        })
