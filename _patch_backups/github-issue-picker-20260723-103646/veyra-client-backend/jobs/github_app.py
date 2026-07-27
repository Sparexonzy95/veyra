from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import jwt
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from jobs.models import GitHubAppInstallation, GitHubRepositoryAccess


STATE_SALT = "veyra.github-app.install.v1"
REQUIRED_PERMISSIONS = {
    "contents": "write",
    "issues": "read",
    "pull_requests": "write",
    "checks": "read",
}
_PERMISSION_LEVEL = {"none": 0, "read": 1, "write": 2, "admin": 3}


class GitHubAppError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallationToken:
    token: str
    expires_at: str
    installation_id: int
    repository_id: int | None = None


def _configured_key_source() -> bool:
    inline = str(getattr(settings, "GITHUB_APP_PRIVATE_KEY", "") or "").strip()
    path = str(getattr(settings, "GITHUB_APP_PRIVATE_KEY_PATH", "") or "").strip()
    return bool(inline or path)


def app_is_configured() -> bool:
    return bool(
        str(getattr(settings, "GITHUB_APP_ID", "") or "").strip()
        and str(getattr(settings, "GITHUB_APP_SLUG", "") or "").strip()
        and _configured_key_source()
        and str(getattr(settings, "GITHUB_WEBHOOK_SECRET", "") or "").strip()
    )


def _private_key() -> str:
    inline = str(getattr(settings, "GITHUB_APP_PRIVATE_KEY", "") or "").strip()
    if inline:
        return inline.replace("\\n", "\n")

    configured_path = str(
        getattr(settings, "GITHUB_APP_PRIVATE_KEY_PATH", "") or ""
    ).strip()
    if not configured_path:
        raise GitHubAppError(
            "Configure GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH."
        )
    path = Path(configured_path).expanduser()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GitHubAppError(
            "The configured GitHub App private-key file could not be read."
        ) from exc
    if not value:
        raise GitHubAppError("The configured GitHub App private-key file is empty.")
    return value


def _api_root() -> str:
    return str(getattr(settings, "GITHUB_API_URL", "https://api.github.com")).rstrip("/")


def _app_jwt() -> str:
    app_id = str(getattr(settings, "GITHUB_APP_ID", "") or "").strip()
    if not app_id:
        raise GitHubAppError("GITHUB_APP_ID is not configured.")
    now = int(time.time())
    return jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": app_id},
        _private_key(),
        algorithm="RS256",
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Veyra-GitHub-App",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request(
    method: str,
    path: str,
    *,
    token: str,
    expected: tuple[int, ...] = (200,),
    json_payload: dict[str, Any] | None = None,
) -> httpx.Response:
    try:
        response = httpx.request(
            method,
            f"{_api_root()}{path}",
            headers=_headers(token),
            json=json_payload,
            timeout=int(getattr(settings, "GITHUB_APP_TIMEOUT_SECONDS", 20)),
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise GitHubAppError("GitHub could not be reached.") from exc
    if response.status_code not in expected:
        detail = ""
        try:
            detail = str(response.json().get("message") or "")
        except (ValueError, AttributeError):
            detail = ""
        raise GitHubAppError(
            f"GitHub request failed ({response.status_code})"
            + (f": {detail}" if detail else ".")
        )
    return response


def create_install_state(*, user_id: str, return_path: str = "/dashboard/jobs") -> str:
    safe_return = return_path if return_path.startswith("/dashboard") else "/dashboard/jobs"
    return signing.dumps(
        {"user_id": str(user_id), "return_path": safe_return},
        salt=STATE_SALT,
        compress=True,
    )


def parse_install_state(state: str, *, user_id: str) -> dict[str, str]:
    try:
        payload = signing.loads(
            state,
            salt=STATE_SALT,
            max_age=int(getattr(settings, "GITHUB_APP_STATE_TTL_SECONDS", 900)),
        )
    except signing.BadSignature as exc:
        raise ValidationError("The GitHub connection request expired or is invalid.") from exc
    if str(payload.get("user_id") or "") != str(user_id):
        raise ValidationError("This GitHub connection belongs to a different Veyra account.")
    return {
        "user_id": str(user_id),
        "return_path": str(payload.get("return_path") or "/dashboard/jobs"),
    }


def install_url(*, user_id: str, return_path: str = "/dashboard/jobs") -> str:
    if not app_is_configured():
        raise GitHubAppError("The Veyra GitHub App is not configured on this server.")
    slug = str(settings.GITHUB_APP_SLUG).strip()
    state = create_install_state(user_id=str(user_id), return_path=return_path)
    configured = str(getattr(settings, "GITHUB_APP_INSTALL_URL", "") or "").strip()
    base = configured or f"https://github.com/apps/{slug}/installations/new"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}state={quote(state)}"


def _permission_satisfies(actual: str, required: str) -> bool:
    return _PERMISSION_LEVEL.get(str(actual or "none").lower(), 0) >= _PERMISSION_LEVEL[required]


def installation_health(*, permissions: dict[str, Any], suspended: bool) -> tuple[str, str]:
    if suspended:
        return GitHubAppInstallation.Status.SUSPENDED, "GitHub suspended this installation."
    missing = [
        f"{name}:{required}"
        for name, required in REQUIRED_PERMISSIONS.items()
        if not _permission_satisfies(str(permissions.get(name) or "none"), required)
    ]
    if missing:
        return (
            GitHubAppInstallation.Status.LIMITED_ACCESS,
            "Required GitHub App permissions are missing: " + ", ".join(missing),
        )
    return GitHubAppInstallation.Status.CONNECTED, "GitHub App access is healthy."


def create_installation_token(
    installation_id: int,
    *,
    repository_id: int | None = None,
    use_cache: bool = True,
) -> InstallationToken:
    cache_key = f"veyra:github-app-token:{installation_id}:{repository_id or 'all'}"
    if use_cache:
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("token"):
            return InstallationToken(**cached)

    payload: dict[str, Any] = {}
    if repository_id is not None:
        payload["repository_ids"] = [int(repository_id)]
    response = _request(
        "POST",
        f"/app/installations/{int(installation_id)}/access_tokens",
        token=_app_jwt(),
        expected=(201,),
        json_payload=payload,
    ).json()
    token = str(response.get("token") or "").strip()
    expires_at = str(response.get("expires_at") or "").strip()
    if not token:
        raise GitHubAppError("GitHub returned no installation token.")
    result = InstallationToken(
        token=token,
        expires_at=expires_at,
        installation_id=int(installation_id),
        repository_id=int(repository_id) if repository_id is not None else None,
    )
    if use_cache:
        cache.set(cache_key, result.__dict__, timeout=50 * 60)
    return result


def _list_installation_repositories(installation_id: int) -> list[dict[str, Any]]:
    access = create_installation_token(installation_id, use_cache=False)
    repositories: list[dict[str, Any]] = []
    page = 1
    while page <= 10:
        response = _request(
            "GET",
            f"/installation/repositories?per_page=100&page={page}",
            token=access.token,
        ).json()
        items = response.get("repositories") or []
        repositories.extend(item for item in items if isinstance(item, dict))
        if len(items) < 100:
            break
        page += 1
    return repositories


@transaction.atomic
def sync_installation(*, client, installation_id: int) -> GitHubAppInstallation:
    payload = _request(
        "GET",
        f"/app/installations/{int(installation_id)}",
        token=_app_jwt(),
    ).json()
    account = payload.get("account") or {}
    permissions = payload.get("permissions") or {}
    suspended = bool(payload.get("suspended_at"))
    status_value, health_message = installation_health(
        permissions=permissions,
        suspended=suspended,
    )

    existing = GitHubAppInstallation.objects.filter(installation_id=int(installation_id)).first()
    if existing and existing.client_id != client.id:
        raise ValidationError("This GitHub App installation is already linked to another Veyra account.")

    installation, _ = GitHubAppInstallation.objects.update_or_create(
        installation_id=int(installation_id),
        defaults={
            "client": client,
            "account_id": int(account.get("id") or 0),
            "account_login": str(account.get("login") or account.get("slug") or "").strip(),
            "account_type": str(account.get("type") or "").strip(),
            "repository_selection": str(payload.get("repository_selection") or "selected"),
            "permissions": permissions,
            "status": status_value,
            "suspended_at": timezone.now() if suspended else None,
            "last_checked_at": timezone.now(),
            "last_error": "" if status_value == GitHubAppInstallation.Status.CONNECTED else health_message,
        },
    )

    repositories = _list_installation_repositories(installation.installation_id)
    seen_ids: set[int] = set()
    for repository in repositories:
        repository_id = int(repository.get("id") or 0)
        if not repository_id:
            continue
        seen_ids.add(repository_id)
        owner = repository.get("owner") or {}
        GitHubRepositoryAccess.objects.update_or_create(
            github_repository_id=repository_id,
            defaults={
                "installation": installation,
                "owner": str(owner.get("login") or "").strip(),
                "name": str(repository.get("name") or "").strip(),
                "full_name": str(repository.get("full_name") or "").strip(),
                "private": bool(repository.get("private")),
                "default_branch": str(repository.get("default_branch") or "main").strip(),
                "html_url": str(repository.get("html_url") or "").strip(),
                "permissions": repository.get("permissions") or {},
                "active": True,
                "last_synced_at": timezone.now(),
            },
        )

    installation.repositories.exclude(github_repository_id__in=seen_ids).update(active=False)
    if not seen_ids and installation.status == GitHubAppInstallation.Status.CONNECTED:
        installation.status = GitHubAppInstallation.Status.LIMITED_ACCESS
        installation.last_error = (
            "The Veyra GitHub App is installed, but no repositories are approved."
        )
        installation.save(update_fields=["status", "last_error", "updated_at"])
    return installation


def repository_access_for_url(*, client, owner: str, repository: str) -> GitHubRepositoryAccess:
    access = (
        GitHubRepositoryAccess.objects.select_related("installation")
        .filter(
            installation__client=client,
            active=True,
            owner__iexact=owner,
            name__iexact=repository,
        )
        .first()
    )
    if not access:
        raise ValidationError(
            "This repository is not connected to Veyra. Install the Veyra GitHub App and grant access to it first."
        )
    if access.installation.status != GitHubAppInstallation.Status.CONNECTED:
        raise ValidationError(
            "The GitHub App connection for this repository is not healthy. Reconnect or refresh it before continuing."
        )
    return access


def token_for_repository(access: GitHubRepositoryAccess) -> InstallationToken:
    if not access.active or access.installation.status != GitHubAppInstallation.Status.CONNECTED:
        raise GitHubAppError("The repository installation is not active.")
    return create_installation_token(
        access.installation.installation_id,
        repository_id=access.github_repository_id,
    )


def verify_webhook_signature(*, body: bytes, signature: str) -> bool:
    secret = str(getattr(settings, "GITHUB_WEBHOOK_SECRET", "") or "").encode("utf-8")
    if not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
