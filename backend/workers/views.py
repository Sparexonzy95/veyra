from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from workers.circle_wallet import (
    WorkerWalletProvisioningError,
    provision_worker_wallet,
)
from workers.engine import connect_worker_engine
from workers.models import WorkerAgent
from workers.permissions import IsVeyraAdmin
from workers.serializers import WorkerAgentSerializer


class WorkerAgentViewSet(viewsets.ModelViewSet):
    queryset = WorkerAgent.objects.select_related("owner_user").all()
    serializer_class = WorkerAgentSerializer
    permission_classes = [IsVeyraAdmin]
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=True, methods=["post"], url_path="connect-engine")
    def connect_engine(self, request, pk=None):
        worker = self.get_object()
        result = connect_worker_engine(worker)
        worker.refresh_from_db()

        payload = {
            "engine": result.as_dict(),
            "worker": self.get_serializer(worker).data,
        }
        response_status = status.HTTP_200_OK if result.connected else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=response_status)

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
        return Response(
            {
                "wallet": result.as_dict(),
                "worker": self.get_serializer(worker).data,
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )
