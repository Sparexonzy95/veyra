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
from workers.execution_transport import (
    ExecutionTransportError,
    execution_task_for_connection,
    repository_credential_for_connection,
    submit_execution_result,
)
from workers.hosted_agent_connection import (
    mark_runtime_heartbeat,
    verify_runtime_credential,
)
from workers.verification_transport import (
    VerificationTransportError,
    repository_credential_for_verifier,
    submit_verifier_result,
    verification_task_for_connection,
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
        job_task = None
        verification_task = None
        if qualification_task is None:
            try:
                job_task = execution_task_for_connection(connection)
            except ExecutionTransportError:
                job_task = None
            if job_task is None:
                try:
                    verification_task = verification_task_for_connection(connection)
                except VerificationTransportError:
                    verification_task = None
        return Response(
            {
                "ok": True,
                "agent_id": str(connection.worker_id),
                "connection_status": connection.status,
                "qualification_task": qualification_task,
                "job_task": job_task,
                "verification_task": verification_task,
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
                    "agent_role": worker.agent_role,
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

class AgentRuntimeJobCredentialView(APIView):
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
            value = repository_credential_for_connection(
                connection,
                assignment_id=str(payload.get("assignment_id") or ""),
                lease_token=str(payload.get("lease_token") or ""),
            )
        except ExecutionTransportError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(value)


class AgentRuntimeJobResultView(APIView):
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
            assignment = submit_execution_result(connection=connection, payload=payload)
        except ExecutionTransportError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            {
                "ok": True,
                "assignment_id": str(assignment.id),
                "assignment_status": assignment.status,
                "queue_status": assignment.queue_item.status,
            }
        )



class AgentRuntimeVerificationCredentialView(APIView):
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
            value = repository_credential_for_verifier(
                connection,
                verification_id=str(payload.get("verification_id") or ""),
                lease_token=str(payload.get("lease_token") or ""),
            )
        except VerificationTransportError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(value)


class AgentRuntimeVerificationResultView(APIView):
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
            value = submit_verifier_result(connection=connection, payload=payload)
        except VerificationTransportError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            {
                "ok": True,
                "verification_id": str(value.id),
                "status": value.status,
                "verdict": value.verdict,
                "worker_assignment_id": str(value.worker_assignment_id),
            }
        )
