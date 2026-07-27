from django.core.cache import cache
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.models import AuditLog
from eth_account import Account
from eth_account.messages import encode_defunct

from workers.runner_auth import (
    PAIRING_SIGNATURE_VERSION,
    RunnerSignatureAuthentication,
    SIGNATURE_VERSION,
    canonical_pairing_message,
)
from workers.runtime_pairing import (
    RuntimePairingError,
    consume_pairing_code,
    record_runner_heartbeat,
)
from workers.runtime_status import runtime_snapshot


class RunnerPairSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32, trim_whitespace=True)
    device_address = serializers.RegexField(r"^0x[a-fA-F0-9]{40}$")
    runner_name = serializers.CharField(max_length=120, trim_whitespace=True)
    runner_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    environment = serializers.DictField(required=False)
    device_signature = serializers.CharField(max_length=160)


class RunnerHeartbeatSerializer(serializers.Serializer):
    runner_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    health = serializers.ChoiceField(choices=["HEALTHY", "UNHEALTHY"], default="HEALTHY")
    health_message = serializers.CharField(max_length=240, required=False, allow_blank=True)
    environment = serializers.DictField(required=False)
    agent_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        max_length=100,
    )


class RunnerPairView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        remote = request.META.get("REMOTE_ADDR", "unknown")
        throttle_key = f"veyra:runner-pair:{remote}"
        attempts = cache.get(throttle_key, 0)
        if attempts >= 20:
            return Response(
                {"detail": "Too many pairing attempts. Wait a few minutes and try again."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        cache.set(throttle_key, attempts + 1, timeout=300)

        serializer = RunnerPairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pair_data = dict(serializer.validated_data)
        signature = pair_data.pop("device_signature")
        pairing_message = canonical_pairing_message(
            code=pair_data["code"],
            device_address=pair_data["device_address"],
            runner_name=pair_data["runner_name"],
        )
        try:
            recovered = Account.recover_message(
                encode_defunct(text=pairing_message),
                signature=signature,
            ).lower()
        except Exception:
            return Response(
                {"detail": "Runner device proof is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if recovered != pair_data["device_address"].lower():
            return Response(
                {"detail": "Runner device proof does not match the supplied device address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = consume_pairing_code(
                raw_code=pair_data.pop("code"),
                **pair_data,
            )
        except RuntimePairingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        cache.delete(throttle_key)
        AuditLog.objects.create(
            actor=result.worker.owner_user,
            action="AGENT_RUNTIME_PAIRED",
            resource_type="WorkerAgent",
            resource_id=str(result.worker.id),
            metadata={
                "runner_id": str(result.runner.id),
                "runner_name": result.runner.name,
            },
        )
        return Response(
            {
                "runner_id": str(result.runner.id),
                "agent": {
                    "id": str(result.worker.id),
                    "name": result.worker.name,
                    "runtime": runtime_snapshot(result.worker),
                },
                "heartbeat_path": "/api/v1/runner/heartbeat/",
                "signature_scheme": SIGNATURE_VERSION,
                "pairing_signature_scheme": PAIRING_SIGNATURE_VERSION,
                "server_time": int(timezone.now().timestamp()),
            },
            status=status.HTTP_201_CREATED,
        )


class RunnerHeartbeatView(APIView):
    authentication_classes = [RunnerSignatureAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RunnerHeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        runner = request.auth
        try:
            workers = record_runner_heartbeat(
                runner=runner,
                payload=serializer.validated_data,
            )
        except RuntimePairingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "status": "accepted",
                "runner_id": str(runner.id),
                "server_time": int(timezone.now().timestamp()),
                "agents": [
                    {
                        "id": str(worker.id),
                        "name": worker.name,
                        "runtime": runtime_snapshot(worker),
                    }
                    for worker in workers
                ],
            }
        )
