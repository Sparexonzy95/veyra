from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from workers.models import WorkerAgent


class GitHubBotConnectionError(RuntimeError):
    """Raised when Veyra cannot safely verify the configured GitHub bot."""


@dataclass(frozen=True)
class GitHubBotConnectionResult:
    connected: bool
    login: str
    github_user_id: int
    account_type: str
    api_url: str
    checked_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _configured_timeout() -> int:
    raw = (os.environ.get("GITHUB_BOT_TIMEOUT_SECONDS") or "20").strip()
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise GitHubBotConnectionError(
            "GITHUB_BOT_TIMEOUT_SECONDS must be a whole number."
        ) from exc

    if not 1 <= timeout <= 120:
        raise GitHubBotConnectionError(
            "GITHUB_BOT_TIMEOUT_SECONDS must be between 1 and 120."
        )
    return timeout


def _safe_error(message: str, token: str) -> str:
    text = str(message or "").replace(token, "[REDACTED]").strip()
    return text[:600] + ("…" if len(text) > 600 else "")


def check_github_bot(*, expected_username: str | None = None) -> GitHubBotConnectionResult:
    """Verify the GitHub token by resolving its authenticated account.

    The token is read only from the runtime environment. It is never returned,
    logged, or stored in the WorkerAgent database record.
    """

    token = (os.environ.get("GITHUB_BOT_TOKEN") or "").strip()
    configured_username = (
        expected_username
        or os.environ.get("GITHUB_BOT_USERNAME")
        or ""
    ).strip()

    if not token:
        raise GitHubBotConnectionError(
            "GITHUB_BOT_TOKEN is missing from the backend .env."
        )
    if not configured_username:
        raise GitHubBotConnectionError(
            "GITHUB_BOT_USERNAME is missing from the backend .env."
        )

    api_url = str(getattr(settings, "GITHUB_API_URL", "https://api.github.com")).rstrip("/")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Veyra-Worker-Agent",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        with httpx.Client(
            headers=headers,
            timeout=_configured_timeout(),
            follow_redirects=False,
        ) as client:
            response = client.get(f"{api_url}/user")
    except httpx.TimeoutException as exc:
        raise GitHubBotConnectionError(
            "GitHub bot verification timed out."
        ) from exc
    except httpx.HTTPError as exc:
        raise GitHubBotConnectionError(
            f"GitHub bot verification failed: {_safe_error(str(exc), token)}"
        ) from exc

    if response.status_code == 401:
        raise GitHubBotConnectionError(
            "GitHub rejected the bot token. Create a new token and update "
            "GITHUB_BOT_TOKEN in .env."
        )
    if response.status_code == 403:
        raise GitHubBotConnectionError(
            "GitHub accepted the request but denied access. Check the token "
            "permissions and account status."
        )
    if response.status_code != 200:
        raise GitHubBotConnectionError(
            f"GitHub returned HTTP {response.status_code} while verifying the bot."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise GitHubBotConnectionError(
            "GitHub returned an invalid response while verifying the bot."
        ) from exc

    login = str(payload.get("login") or "").strip()
    user_id = payload.get("id")
    account_type = str(payload.get("type") or "").strip()
    returned_api_url = str(payload.get("url") or f"{api_url}/users/{login}").strip()

    if not login or not isinstance(user_id, int):
        raise GitHubBotConnectionError(
            "GitHub did not return a valid authenticated account."
        )
    if login.casefold() != configured_username.casefold():
        raise GitHubBotConnectionError(
            f"The token belongs to '{login}', not '{configured_username}'. "
            "Refusing to connect the wrong GitHub account."
        )
    if account_type not in {"User", "Bot"}:
        raise GitHubBotConnectionError(
            f"Unsupported GitHub account type: {account_type or 'unknown'}."
        )

    return GitHubBotConnectionResult(
        connected=True,
        login=login,
        github_user_id=user_id,
        account_type=account_type,
        api_url=returned_api_url,
        checked_at=timezone.now().isoformat(),
    )


def connect_worker_github(
    worker: WorkerAgent,
    *,
    expected_username: str | None = None,
) -> GitHubBotConnectionResult:
    """Verify and attach a dedicated GitHub bot account to a worker."""

    worker.refresh_from_db()

    if not worker.engine_connected:
        raise GitHubBotConnectionError(
            "Connect the coding engine before connecting GitHub."
        )
    if not worker.circle_wallet_id or not worker.worker_wallet_address:
        raise GitHubBotConnectionError(
            "Create the worker wallet before connecting GitHub."
        )
    if not worker.payout_wallet_address:
        raise GitHubBotConnectionError(
            "Assign the worker payout wallet before connecting GitHub."
        )

    result = check_github_bot(expected_username=expected_username)

    if (
        worker.github_connected
        and worker.github_username
        and worker.github_username.casefold() != result.login.casefold()
    ):
        raise GitHubBotConnectionError(
            "This worker is already connected to a different GitHub account."
        )

    worker.github_username = result.login
    worker.github_connected = True

    if worker.status in {
        WorkerAgent.Status.SETUP_REQUIRED,
        WorkerAgent.Status.PROFILE_READY,
        WorkerAgent.Status.ENGINE_CONNECTED,
        WorkerAgent.Status.WALLET_READY,
        WorkerAgent.Status.PAYOUT_READY,
        WorkerAgent.Status.GITHUB_READY,
    }:
        worker.status = WorkerAgent.Status.GITHUB_READY

    worker.save(
        update_fields=[
            "github_username",
            "github_connected",
            "status",
            "discovery_enabled",
            "updated_at",
        ]
    )
    return result
