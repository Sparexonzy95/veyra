from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import HasClientCapability
from jobs.github_app import (
    GitHubAppError,
    app_is_configured,
    install_url,
    github_ci_preflight,
    list_repository_issues,
    parse_install_state,
    sync_installation,
    verify_webhook_signature,
)
from jobs.models import GitHubAppInstallation, GitHubRepositoryAccess

logger = logging.getLogger(__name__)


def _installation_payload(item: GitHubAppInstallation) -> dict:
    return {
        "id": str(item.id),
        "installation_id": item.installation_id,
        "account_login": item.account_login,
        "account_type": item.account_type,
        "repository_selection": item.repository_selection,
        "permissions": item.permissions,
        "status": item.status,
        "last_checked_at": item.last_checked_at,
        "last_error": item.last_error,
    }


def _repository_payload(item: GitHubRepositoryAccess) -> dict:
    return {
        "id": str(item.id),
        "installation_id": str(item.installation_id),
        "github_repository_id": item.github_repository_id,
        "owner": item.owner,
        "name": item.name,
        "full_name": item.full_name,
        "private": item.private,
        "default_branch": item.default_branch,
        "html_url": item.html_url,
        "permissions": item.permissions,
        "active": item.active,
        "last_synced_at": item.last_synced_at,
    }


class GitHubConnectionStatusView(APIView):
    permission_classes = [HasClientCapability]

    def get(self, request):
        installations = list(
            GitHubAppInstallation.objects.filter(client=request.user).order_by("account_login")
        )
        repositories = list(
            GitHubRepositoryAccess.objects.select_related("installation")
            .filter(installation__client=request.user, active=True)
            .order_by("full_name")
        )
        healthy_installation_ids = {
            item.id
            for item in installations
            if item.status == GitHubAppInstallation.Status.CONNECTED
        }
        connected = bool(
            healthy_installation_ids
            and any(item.installation_id in healthy_installation_ids for item in repositories)
        )
        return Response(
            {
                "configured": app_is_configured(),
                "app_slug": str(getattr(settings, "GITHUB_APP_SLUG", "") or ""),
                "connected": connected,
                "connection_state": (
                    GitHubAppInstallation.Status.CONNECTED
                    if connected
                    else (installations[0].status if installations else GitHubAppInstallation.Status.DISCONNECTED)
                ),
                "installations": [_installation_payload(item) for item in installations],
                "repositories": [_repository_payload(item) for item in repositories],
            }
        )


class GitHubInstallStartView(APIView):
    permission_classes = [HasClientCapability]

    def post(self, request):
        return_path = str(request.data.get("return_path") or "/dashboard/jobs")
        try:
            url = install_url(user_id=str(request.user.id), return_path=return_path)
        except GitHubAppError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"install_url": url})


class GitHubInstallCompleteView(APIView):
    permission_classes = [HasClientCapability]

    def post(self, request):
        state_value = str(request.data.get("state") or "").strip()
        raw_installation_id = str(request.data.get("installation_id") or "").strip()
        # `setup_action` describes what the user did on GitHub ("install",
        # "update", "request"). It is never an OAuth code and is never treated
        # as one: it is recorded for diagnostics only and takes no part in
        # authenticating or identifying the installation.
        setup_action = str(request.data.get("setup_action") or "").strip()

        # Diagnostics record which fields arrived and whether they parsed, never
        # their values, so the signed state cannot end up in the server log.
        logger.info(
            "github install complete: fields=%s setup_action=%s",
            sorted(k for k in request.data.keys()),
            setup_action or "(none)",
        )

        if not state_value or not raw_installation_id:
            missing = [
                name
                for name, present in (
                    ("state", bool(state_value)),
                    ("installation_id", bool(raw_installation_id)),
                )
                if not present
            ]
            logger.warning("github install complete rejected: missing=%s", missing)
            return Response(
                {
                    "detail": "GitHub returned an incomplete installation callback.",
                    "missing_fields": missing,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # GitHub sends the installation id as a numeric string. Convert it here
        # so a malformed value produces a clear 400 instead of surfacing as an
        # unrelated 409 from the sync path below.
        try:
            installation_id = int(raw_installation_id)
        except (TypeError, ValueError):
            logger.warning("github install complete rejected: installation_id not numeric")
            return Response(
                {"detail": "GitHub returned an invalid installation identifier."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        state_payload = parse_install_state(state_value, user_id=str(request.user.id))
        try:
            installation = sync_installation(
                client=request.user,
                installation_id=installation_id,
            )
        except (GitHubAppError, ValueError) as exc:
            logger.warning("github install sync failed for user %s", request.user.id)
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        repositories = installation.repositories.filter(active=True).order_by("full_name")
        return Response(
            {
                "installation": _installation_payload(installation),
                "repositories": [_repository_payload(item) for item in repositories],
                "return_path": state_payload["return_path"],
            }
        )


class GitHubRepositoryIssueListView(APIView):
    permission_classes = [HasClientCapability]

    def get(self, request, repository_access_id):
        repository = (
            GitHubRepositoryAccess.objects.select_related("installation")
            .filter(
                id=repository_access_id,
                installation__client=request.user,
                active=True,
            )
            .first()
        )
        if not repository:
            return Response(
                {"detail": "Approved GitHub repository was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if repository.installation.status != GitHubAppInstallation.Status.CONNECTED:
            return Response(
                {
                    "detail": (
                        "The GitHub App connection for this repository is not healthy. "
                        "Reconnect or refresh it before loading issues."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        selected_state = str(request.query_params.get("state") or "open").lower()
        try:
            issues = list_repository_issues(repository, state=selected_state)
        except GitHubAppError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "repository": _repository_payload(repository),
                "issues": issues,
            }
        )


class GitHubRepositoryCiPreflightView(APIView):
    permission_classes = [HasClientCapability]

    def get(self, request, repository_access_id):
        repository = (
            GitHubRepositoryAccess.objects.select_related("installation")
            .filter(
                id=repository_access_id,
                installation__client=request.user,
                active=True,
            )
            .first()
        )
        if not repository:
            return Response(
                {"detail": "Approved GitHub repository was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if repository.installation.status != GitHubAppInstallation.Status.CONNECTED:
            return Response(
                {
                    "detail": (
                        "The GitHub App connection for this repository is not healthy. "
                        "Reconnect or refresh it before checking CI."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        branch = str(request.query_params.get("branch") or repository.default_branch or "main").strip()
        try:
            result = github_ci_preflight(repository, branch=branch)
        except GitHubAppError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(result)


class GitHubInstallationRefreshView(APIView):
    permission_classes = [HasClientCapability]

    def post(self, request, installation_id):
        record = GitHubAppInstallation.objects.filter(
            id=installation_id,
            client=request.user,
        ).first()
        if not record:
            return Response({"detail": "GitHub installation was not found."}, status=404)
        try:
            installation = sync_installation(
                client=request.user,
                installation_id=record.installation_id,
            )
        except GitHubAppError as exc:
            record.status = GitHubAppInstallation.Status.CREDENTIAL_GENERATION_FAILED
            record.last_error = str(exc)[:1000]
            record.save(update_fields=["status", "last_error", "updated_at"])
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({"installation": _installation_payload(installation)})


class GitHubInstallationDisconnectView(APIView):
    permission_classes = [HasClientCapability]

    def post(self, request, installation_id):
        record = GitHubAppInstallation.objects.filter(
            id=installation_id,
            client=request.user,
        ).first()
        if not record:
            return Response({"detail": "GitHub installation was not found."}, status=404)
        record.status = GitHubAppInstallation.Status.DISCONNECTED
        record.last_error = "Disconnected in Veyra. Remove the app in GitHub to revoke access completely."
        record.repositories.update(active=False)
        record.save(update_fields=["status", "last_error", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class GitHubWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not verify_webhook_signature(
            body=request.body,
            signature=str(request.headers.get("X-Hub-Signature-256") or ""),
        ):
            return Response({"detail": "Invalid GitHub webhook signature."}, status=401)

        event = str(request.headers.get("X-GitHub-Event") or "")
        payload = request.data if isinstance(request.data, dict) else {}
        installation_data = payload.get("installation") or {}
        installation_id = installation_data.get("id")
        if not installation_id:
            return Response({"accepted": True, "event": event})

        record = GitHubAppInstallation.objects.filter(installation_id=int(installation_id)).first()
        if not record:
            return Response({"accepted": True, "event": event})

        action = str(payload.get("action") or "")
        if event == "installation":
            if action == "deleted":
                record.status = GitHubAppInstallation.Status.DISCONNECTED
                record.last_error = "The GitHub App installation was removed."
                record.repositories.update(active=False)
                record.save(update_fields=["status", "last_error", "updated_at"])
            elif action == "suspend":
                record.status = GitHubAppInstallation.Status.SUSPENDED
                record.last_error = "The GitHub App installation was suspended."
                record.save(update_fields=["status", "last_error", "updated_at"])
            elif action in {"unsuspend", "new_permissions_accepted", "created"}:
                try:
                    sync_installation(client=record.client, installation_id=record.installation_id)
                except GitHubAppError:
                    pass
        elif event == "installation_repositories":
            try:
                sync_installation(client=record.client, installation_id=record.installation_id)
            except GitHubAppError:
                pass

        return Response({"accepted": True, "event": event})
