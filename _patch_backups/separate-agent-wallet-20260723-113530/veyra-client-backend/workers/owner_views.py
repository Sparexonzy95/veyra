from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.models import AuditLog
from workers.circle_wallet import WorkerWalletProvisioningError, provision_worker_wallet
from workers.hosted_runtime import (
    HostedRuntimeProvisioningError,
    ensure_hosted_runtime,
    is_hosted_runtime,
)
from workers.models import WorkerAgent
from workers.permissions import IsAgentOwner
from workers.runtime_pairing import (
    RuntimePairingError,
    create_pairing_code,
    revoke_agent_runtime,
)
from workers.runtime_status import runtime_snapshot
from workers.serializers import AgentOwnerWorkerSerializer


class AgentOwnerWorkerViewSet(viewsets.ModelViewSet):
    """Owner-scoped control-plane API for external agents.

    This API deliberately exposes no GitHub token, Circle credential, wallet-set
    identifier, entity secret, or model credential.
    """

    serializer_class = AgentOwnerWorkerSerializer
    permission_classes = [IsAgentOwner]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = WorkerAgent.objects.select_related("owner_user", "runtime_binding__runner").filter(
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
        )
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return queryset
        return queryset.filter(owner_user=user)

    def perform_create(self, serializer):
        worker = serializer.save()
        AuditLog.objects.create(
            actor=self.request.user,
            action="AGENT_PROFILE_CREATED",
            resource_type="WorkerAgent",
            resource_id=str(worker.id),
        )

    def perform_update(self, serializer):
        worker = serializer.save()
        AuditLog.objects.create(
            actor=self.request.user,
            action="AGENT_PROFILE_UPDATED",
            resource_type="WorkerAgent",
            resource_id=str(worker.id),
        )


    @action(detail=True, methods=["post"], url_path="runtime/hosted/provision")
    def provision_hosted_runtime(self, request, pk=None):
        worker = self.get_object()
        try:
            result = ensure_hosted_runtime(worker)
        except HostedRuntimeProvisioningError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        worker.refresh_from_db()
        AuditLog.objects.create(
            actor=request.user,
            action=(
                "AGENT_HOSTED_RUNTIME_PROVISIONED"
                if result.created
                else "AGENT_HOSTED_RUNTIME_REPAIRED"
            ),
            resource_type="WorkerAgent",
            resource_id=str(worker.id),
            metadata={"runtime_mode": "VEYRA_HOSTED"},
        )
        return Response(
            {
                "runtime": runtime_snapshot(worker),
                "agent": self.get_serializer(worker).data,
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="runtime/pairing-code")
    def create_runtime_pairing_code(self, request, pk=None):
        worker = self.get_object()
        if is_hosted_runtime(worker):
            return Response(
                {
                    "detail": (
                        "This agent uses a Veyra-hosted runtime. Owner-hosted "
                        "pairing is an advanced mode and is not enabled in the MVP."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            raw_code, record = create_pairing_code(
                worker=worker,
                owner_user=request.user,
            )
        except RuntimePairingError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        AuditLog.objects.create(
            actor=request.user,
            action="AGENT_RUNTIME_PAIRING_CODE_CREATED",
            resource_type="WorkerAgent",
            resource_id=str(worker.id),
            metadata={"expires_at": record.expires_at.isoformat()},
        )
        return Response(
            {
                "pairing_code": raw_code,
                "expires_at": record.expires_at,
                "agent": {
                    "id": str(worker.id),
                    "name": worker.name,
                },
                "instructions": "Open Veyra Runner and enter this one-time code.",
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="runtime/status")
    def runtime_status(self, request, pk=None):
        worker = self.get_object()
        return Response({"runtime": runtime_snapshot(worker)})

    @action(detail=True, methods=["post"], url_path="runtime/revoke")
    def revoke_runtime(self, request, pk=None):
        worker = self.get_object()
        if is_hosted_runtime(worker):
            return Response(
                {"detail": "Veyra-hosted runtimes are managed automatically."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            revoke_agent_runtime(worker=worker, owner_user=request.user)
        except RuntimePairingError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        worker.refresh_from_db()
        AuditLog.objects.create(
            actor=request.user,
            action="AGENT_RUNTIME_REVOKED",
            resource_type="WorkerAgent",
            resource_id=str(worker.id),
        )
        return Response(
            {
                "runtime": runtime_snapshot(worker),
                "agent": self.get_serializer(worker).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="create-wallet")
    def create_wallet(self, request, pk=None):
        worker = self.get_object()
        try:
            result = provision_worker_wallet(worker)
        except WorkerWalletProvisioningError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        worker.refresh_from_db()
        AuditLog.objects.create(
            actor=request.user,
            action="AGENT_WALLET_CREATED" if result.created else "AGENT_WALLET_REUSED",
            resource_type="WorkerAgent",
            resource_id=str(worker.id),
            metadata={
                "wallet_role": "AGENT_OPERATIONAL",
                "custody_type": "DEVELOPER_CONTROLLED",
                "blockchain": result.blockchain,
            },
        )
        return Response(
            {
                "wallet": {
                    "address": result.address,
                    "blockchain": result.blockchain,
                    "account_type": result.account_type,
                    "created": result.created,
                },
                "agent": self.get_serializer(worker).data,
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )
