from __future__ import annotations

import base64
import hashlib
import hmac
import re
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
    """Create a signed state token for GitHub App installation flow.

    The return_path is preserved if it starts with /client/ or /dashboard/,
    otherwise defaults to /dashboard/jobs for safety.
    """
    safe_return = (
        return_path
        if (return_path.startswith("/client/") or return_path.startswith("/dashboard"))
        else "/dashboard/jobs"
    )
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
    """Build the GitHub App *installation* URL the browser should be sent to.

    The result is always of the form:

        https://github.com/apps/<slug>/installations/new?state=<signed-state>

    Two mistakes are rejected outright rather than allowed to fail later as a
    confusing empty callback:

    * a missing app slug, which would otherwise produce
      ``https://github.com/apps//installations/new`` - a GitHub 404 that
      bounces the user back with no installation parameters at all;
    * an OAuth authorisation endpoint in ``GITHUB_APP_INSTALL_URL``. OAuth
      authorisation and app installation are different flows: the former
      returns only ``code``, never ``installation_id``, so the installation
      could never be linked.
    """
    slug = str(getattr(settings, "GITHUB_APP_SLUG", "") or "").strip().strip("/")
    if not app_is_configured():
        # Name the missing settings. "Not configured" on its own sends people
        # looking at GitHub, when the answer is a blank value on this server.
        missing = [
            name
            for name, present in (
                ("GITHUB_APP_ID", bool(str(getattr(settings, "GITHUB_APP_ID", "") or "").strip())),
                ("GITHUB_APP_SLUG", bool(slug)),
                ("GITHUB_APP_PRIVATE_KEY (or GITHUB_APP_PRIVATE_KEY_PATH)", _configured_key_source()),
                (
                    "GITHUB_WEBHOOK_SECRET",
                    bool(str(getattr(settings, "GITHUB_WEBHOOK_SECRET", "") or "").strip()),
                ),
            )
            if not present
        ]
        detail = ", ".join(missing) if missing else "one or more GitHub App settings"
        raise GitHubAppError(
            f"The Veyra GitHub App is not configured on this server. Missing: {detail}."
        )

    if not slug:
        raise GitHubAppError(
            "GITHUB_APP_SLUG is not set, so the Veyra GitHub App installation URL "
            "cannot be built. Set it to the app's slug exactly as it appears in "
            "its GitHub URL (github.com/apps/<slug>)."
        )

    configured = str(getattr(settings, "GITHUB_APP_INSTALL_URL", "") or "").strip()
    if configured:
        lowered = configured.lower()
        if "/login/oauth/authorize" in lowered:
            raise GitHubAppError(
                "GITHUB_APP_INSTALL_URL points at the OAuth authorisation endpoint. "
                "GitHub App installation must use "
                "https://github.com/apps/<slug>/installations/new, which is the only "
                "flow that returns an installation_id."
            )
        if "/installations/new" not in lowered:
            raise GitHubAppError(
                "GITHUB_APP_INSTALL_URL must be the app's installation URL ending in "
                "/installations/new."
            )
        base = configured
    else:
        base = f"https://github.com/apps/{slug}/installations/new"

    state = create_install_state(user_id=str(user_id), return_path=return_path)
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
    permissions: dict[str, str] | None = None,
    use_cache: bool = True,
) -> InstallationToken:
    permission_key = ",".join(
        f"{key}:{value}" for key, value in sorted((permissions or {}).items())
    ) or "default"
    cache_key = (
        f"veyra:github-app-token:{installation_id}:"
        f"{repository_id or 'all'}:{permission_key}"
    )
    if use_cache:
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("token"):
            return InstallationToken(**cached)

    payload: dict[str, Any] = {}
    if repository_id is not None:
        payload["repository_ids"] = [int(repository_id)]
    if permissions:
        payload["permissions"] = {
            str(key): str(value) for key, value in permissions.items()
        }
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


def token_for_repository(
    access: GitHubRepositoryAccess,
    *,
    permissions: dict[str, str] | None = None,
    use_cache: bool = True,
) -> InstallationToken:
    if not access.active or access.installation.status != GitHubAppInstallation.Status.CONNECTED:
        raise GitHubAppError("The repository installation is not active.")
    return create_installation_token(
        access.installation.installation_id,
        repository_id=access.github_repository_id,
        permissions=permissions,
        use_cache=use_cache,
    )


def list_repository_issues(
    access: GitHubRepositoryAccess,
    *,
    state: str = "open",
) -> list[dict[str, Any]]:
    """Return repository issues without pull requests.

    GitHub's issues endpoint also returns pull requests, so those entries are
    removed before the response reaches the client job form.
    """
    selected_state = state if state in {"open", "closed", "all"} else "open"
    token = token_for_repository(access)
    owner = quote(access.owner, safe="")
    repository = quote(access.name, safe="")
    response = _request(
        "GET",
        (
            f"/repos/{owner}/{repository}/issues"
            f"?state={selected_state}&sort=updated&direction=desc&per_page=100"
        ),
        token=token.token,
    )

    payload = response.json()
    if not isinstance(payload, list):
        raise GitHubAppError("GitHub returned an invalid issue list.")

    issues: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("pull_request"):
            continue
        labels = [
            str(label.get("name") or "").strip()
            for label in (item.get("labels") or [])
            if isinstance(label, dict) and str(label.get("name") or "").strip()
        ]
        author = item.get("user") or {}
        issues.append(
            {
                "number": int(item.get("number") or 0),
                "title": str(item.get("title") or "").strip(),
                "state": str(item.get("state") or selected_state),
                "html_url": str(item.get("html_url") or "").strip(),
                "updated_at": str(item.get("updated_at") or ""),
                "author_login": str(author.get("login") or "").strip(),
                "labels": labels,
            }
        )
    return [item for item in issues if item["number"] and item["html_url"]]



def _workflow_has_automatic_code_trigger(content: str) -> bool:
    """Return True when a GitHub Actions workflow can run for code changes.

    Veyra accepts workflows triggered by a pull request or by a push. The worker
    pushes the exact execution commit before opening the PR, so either trigger
    can legitimately produce a Check Run for the commit Veyra later verifies.
    Manual-only/scheduled workflows do not qualify for pre-funding readiness.
    """

    normalized = str(content or "")
    if not normalized.strip():
        return False

    scalar = re.search(
        r"(?im)^[ \t]*[\"']?on[\"']?[ \t]*:[ \t]*[\"']?(?:push|pull_request|pull_request_target)[\"']?[ \t]*(?:#.*)?$",
        normalized,
    )
    if scalar:
        return True

    inline = re.search(
        r"(?im)^[ \t]*[\"']?on[\"']?[ \t]*:[ \t]*\[[^\]]*\b(?:push|pull_request|pull_request_target)\b",
        normalized,
    )
    if inline:
        return True

    block = re.search(
        r"(?im)^[ \t]*[\"']?on[\"']?[ \t]*:[ \t]*(?:#[^\n]*)?\n"
        r"(?P<body>(?:(?:[ \t]+[^\n]*)(?:\n|$))*)",
        normalized,
    )
    if not block:
        return False
    return bool(
        re.search(
            r"(?im)^[ \t]+[\"']?(?:push|pull_request|pull_request_target)[\"']?[ \t]*:",
            block.group("body"),
        )
    )


def _decode_github_content(payload: dict[str, Any]) -> str:
    if str(payload.get("encoding") or "").lower() != "base64":
        return ""
    raw = str(payload.get("content") or "").replace("\n", "")
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def github_ci_preflight(
    access: GitHubRepositoryAccess,
    *,
    branch: str | None = None,
) -> dict[str, Any]:
    """Prove that a repository can produce GitHub Check Runs before funding.

    This is deliberately a readiness check, not a promise that future CI will
    pass. It prevents a client from locking `requireGithubChecks=true` into an
    escrow when Veyra has no evidence that the repository can produce checks.

    Readiness is satisfied by either:
      * an automatic GitHub Actions workflow triggered by push / pull request;
      * existing Check Run history on the selected branch head from any provider.

    Veyra still verifies the exact submitted commit after the worker opens the
    PR. A historical check here never counts as settlement evidence.
    """

    if not access.active or access.installation.status != GitHubAppInstallation.Status.CONNECTED:
        raise GitHubAppError("The repository installation is not active.")

    permissions = access.installation.permissions or {}
    checks_permission = _permission_satisfies(
        str(permissions.get("checks") or "none"),
        "read",
    )
    if not checks_permission:
        return {
            "repository_id": str(access.id),
            "repository": access.full_name,
            "branch": str(branch or access.default_branch or "main"),
            "ready": False,
            "checks_permission": False,
            "workflow_files": [],
            "automatic_workflows": [],
            "recent_check_runs": [],
            "source": "MISSING_CHECKS_PERMISSION",
            "message": "The Veyra GitHub App cannot read Check Runs for this repository.",
        }

    token = token_for_repository(access)
    owner = quote(access.owner, safe="")
    repository = quote(access.name, safe="")
    selected_branch = str(branch or access.default_branch or "main").strip() or "main"
    encoded_branch = quote(selected_branch, safe="")

    workflow_response = _request(
        "GET",
        f"/repos/{owner}/{repository}/contents/.github/workflows?ref={encoded_branch}",
        token=token.token,
        expected=(200, 404),
    )
    workflow_files: list[str] = []
    automatic_workflows: list[str] = []
    if workflow_response.status_code == 200:
        payload = workflow_response.json()
        if isinstance(payload, list):
            workflow_items = [
                item
                for item in payload[:50]
                if isinstance(item, dict)
                and str(item.get("type") or "") == "file"
                and str(item.get("name") or "").lower().endswith((".yml", ".yaml"))
            ]
            for item in workflow_items:
                name = str(item.get("name") or "").strip()
                path = str(item.get("path") or "").strip()
                if not name or not path:
                    continue
                workflow_files.append(name)
                file_response = _request(
                    "GET",
                    f"/repos/{owner}/{repository}/contents/{quote(path, safe='/')}?ref={encoded_branch}",
                    token=token.token,
                    expected=(200, 404),
                )
                if file_response.status_code != 200:
                    continue
                file_payload = file_response.json()
                if isinstance(file_payload, dict) and _workflow_has_automatic_code_trigger(
                    _decode_github_content(file_payload)
                ):
                    automatic_workflows.append(name)

    branch_response = _request(
        "GET",
        f"/repos/{owner}/{repository}/branches/{encoded_branch}",
        token=token.token,
        expected=(200, 404),
    )
    head_sha = ""
    if branch_response.status_code == 200:
        branch_payload = branch_response.json()
        if isinstance(branch_payload, dict):
            head_sha = str((branch_payload.get("commit") or {}).get("sha") or "").strip().lower()

    recent_check_runs: list[dict[str, str]] = []
    if head_sha:
        checks_response = _request(
            "GET",
            f"/repos/{owner}/{repository}/commits/{quote(head_sha, safe='')}/check-runs?per_page=100",
            token=token.token,
            expected=(200,),
        )
        checks_payload = checks_response.json()
        checks = checks_payload.get("check_runs") if isinstance(checks_payload, dict) else []
        for item in (checks or [])[:20]:
            if not isinstance(item, dict):
                continue
            app = item.get("app") or {}
            recent_check_runs.append(
                {
                    "name": str(item.get("name") or "")[:160],
                    "status": str(item.get("status") or "")[:40],
                    "conclusion": str(item.get("conclusion") or "")[:40],
                    "app": str(app.get("slug") or app.get("name") or "")[:120],
                }
            )

    ready = bool(automatic_workflows or recent_check_runs)
    if automatic_workflows:
        source = "AUTOMATIC_WORKFLOW"
        message = (
            "GitHub CI is ready. Veyra found an automatic workflow that can create "
            "Check Runs when the worker pushes or opens a pull request."
        )
    elif recent_check_runs:
        source = "EXISTING_CHECK_PROVIDER"
        message = (
            "GitHub CI is ready. Veyra found existing Check Run history from a connected provider."
        )
    elif workflow_files:
        source = "WORKFLOW_NOT_AUTOMATIC"
        message = (
            "GitHub workflow files exist, but Veyra could not confirm a push or pull-request trigger. "
            "Configure automatic CI or choose Veyra verification without required GitHub CI."
        )
    else:
        source = "NO_CI_EVIDENCE"
        message = (
            "No GitHub CI configuration or existing Check Run provider was detected for this branch. "
            "Configure CI first or choose Veyra verification without required GitHub CI."
        )

    return {
        "repository_id": str(access.id),
        "repository": access.full_name,
        "branch": selected_branch,
        "ready": ready,
        "checks_permission": checks_permission,
        "workflow_files": workflow_files,
        "automatic_workflows": automatic_workflows,
        "recent_check_runs": recent_check_runs,
        "source": source,
        "message": message,
    }

def verify_webhook_signature(*, body: bytes, signature: str) -> bool:
    secret = str(getattr(settings, "GITHUB_WEBHOOK_SECRET", "") or "").encode("utf-8")
    if not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
