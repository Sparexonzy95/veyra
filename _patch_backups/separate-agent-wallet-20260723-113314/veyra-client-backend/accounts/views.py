from django.conf import settings
from drf_spectacular.utils import OpenApiTypes, extend_schema
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from common.models import AuditLog
from accounts.models import ClientProfile, PendingCircleAuth, UserCapability, VeyraSession
from accounts.serializers import AgentOwnerOnboardingSerializer, CircleExchangeSerializer, ClientOnboardingSerializer, EmailRequestSerializer, SocialDeviceSerializer
from accounts.services import (
    bind_identity_and_wallet_user, clear_auth_cookies, create_pending_circle_auth, get_pending_from_request,
    grant_agent_owner, grant_client, issue_session, set_onboarding_cookie, set_session_cookie,
)
from wallets.circle import CircleClient, CircleError
from wallets.services import select_arc_wallet

class CircleSocialDeviceView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=SocialDeviceSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = SocialDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(CircleClient().create_social_device_token(serializer.validated_data['device_id']))

class CircleEmailRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=EmailRequestSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = EmailRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(CircleClient().create_email_token(data['device_id'], data['email']))

class CircleExchangeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=CircleExchangeSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = CircleExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        circle = CircleClient()
        try:
            wallets = circle.list_wallets(data['user_token'])
        except CircleError as exc:
            raise AuthenticationFailed('Circle session could not be validated.') from exc

        arc_wallet = select_arc_wallet(wallets)
        if arc_wallet:
            try:
                user, wallet = bind_identity_and_wallet_user(
                    wallet=arc_wallet,
                    pending=None,
                    circle_user_id=data.get('circle_user_id', ''),
                    method=data['auth_method'],
                    email=data.get('email', ''),
                    display_name=data.get('display_name', ''),
                )
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
            wallet = request.user.wallet_accounts.filter(blockchain=settings.ARC_BLOCKCHAIN).first()
            return Response({
                'authenticated': True,
                'user': {'id': request.user.id, 'display_name': request.user.display_name, 'email': request.user.email},
                'capabilities': capabilities,
                'wallet': {'address': wallet.address, 'blockchain': wallet.blockchain} if wallet else None,
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
            return Response({'capability': 'CLIENT', 'wallet_setup_required': not request.user.wallet_accounts.exists()})

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
            grant_agent_owner(request.user)
            AuditLog.objects.create(
                actor=request.user,
                action='AGENT_OWNER_CAPABILITY_GRANTED',
            )
            return Response({
                'capability': UserCapability.Code.AGENT_OWNER,
                'wallet_setup_required': not request.user.wallet_accounts.exists(),
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
            'wallet_setup_required': True,
        })
