from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from workers.automatic_qualification import (
    AutomaticQualificationError,
    qualification_task_for_connection,
    submit_automatic_qualification,
)
from workers.hosted_agent_connection import (
    mark_runtime_heartbeat,
    verify_runtime_credential,
)
from workers.models import HostedAgentConnection


def _bearer_token(request) -> str:
    value = str(request.headers.get("Authorization") or "").strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value[7:].strip()


def _authenticated_connection(request):
    raw_agent_id = request.query_params.get("agent_id")
    if not raw_agent_id and hasattr(request, "data"):
        raw_agent_id = request.data.get("agent_id")
    agent_id = str(raw_agent_id or "").strip()
    if not agent_id:
        agent_id = str(request.headers.get("X-Veyra-Agent-ID") or "").strip()
    token = _bearer_token(request)
    if not agent_id or not token:
        return None
    connection = (
        HostedAgentConnection.objects.select_related("worker")
        .filter(
            worker_id=agent_id,
            status__in=[
                HostedAgentConnection.Status.CONNECTED,
                HostedAgentConnection.Status.UNHEALTHY,
            ],
        )
        .first()
    )
    if not connection or not verify_runtime_credential(connection, token):
        return None
    return connection


class AgentRuntimeHeartbeatView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        connection = _authenticated_connection(request)
        if connection is None:
            return Response(
                {"detail": "Invalid hosted-agent runtime credential."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        payload = request.data if isinstance(request.data, dict) else {}
        mark_runtime_heartbeat(connection=connection, payload=payload)
        connection.refresh_from_db()
        qualification_task = qualification_task_for_connection(connection)
        return Response(
            {
                "ok": True,
                "agent_id": str(connection.worker_id),
                "connection_status": connection.status,
                "qualification_task": qualification_task,
            }
        )


class AgentRuntimeConfigurationView(APIView):
    """Return only owner-safe execution policy to the authenticated runtime."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        connection = _authenticated_connection(request)
        if connection is None:
            return Response(
                {"detail": "Invalid hosted-agent runtime credential."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        worker = connection.worker
        return Response(
            {
                "agent": {
                    "id": str(worker.id),
                    "name": worker.name,
                    "specialisation": worker.specialisation,
                    "languages": worker.languages,
                    "frameworks": worker.frameworks,
                    "testing_tools": worker.testing_tools,
                    "task_types": worker.task_types,
                    "maximum_active_jobs": worker.maximum_active_jobs,
                    "maximum_execution_minutes": worker.maximum_execution_minutes,
                    "allow_new_dependencies": worker.allow_new_dependencies,
                    "allow_database_migrations": worker.allow_database_migrations,
                    "protected_paths": worker.protected_paths,
                },
                "runtime": {
                    "provider": connection.provider,
                    "model": connection.model_name,
                    "protocol_version": connection.protocol_version,
                },
            }
        )


class AgentRuntimeQualificationSubmitView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        connection = _authenticated_connection(request)
        if connection is None:
            return Response(
                {"detail": "Invalid hosted-agent runtime credential."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        payload = request.data if isinstance(request.data, dict) else {}
        try:
            run, passed = submit_automatic_qualification(
                connection=connection,
                payload=payload,
            )
        except AutomaticQualificationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        run.worker.refresh_from_db()
        return Response(
            {
                "ok": True,
                "qualification_id": str(run.id),
                "qualification_status": run.status,
                "passed": passed,
                "agent_status": run.worker.status,
                "provisioning_stage": run.worker.provisioning_stage,
            }
        )
