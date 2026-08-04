from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from jobs.github_app import GitHubAppError, token_for_repository
from jobs.models import VeyraJob
from workers.models import WorkerAgent


class GitHubFreshnessError(RuntimeError):
    """Raised when GitHub freshness cannot be established safely."""


@dataclass(frozen=True)
class GitHubFreshnessResult:
    passed: bool
    code: str
    detail: str
    issue_state: str
    issue_url: str
    existing_pull_request_url: str = ""
    existing_pull_request_state: str = ""
    existing_branch: str = ""
    checked_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubFreshnessGuard:
    """Read-only GitHub guard used immediately before a job can be queued.

    The guard only uses public repository metadata and the runtime GitHub bot
    token. It never writes to GitHub and never returns or stores the token.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        api_url: str | None = None,
        timeout_seconds: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = (token if token is not None else os.environ.get("GITHUB_BOT_TOKEN", "")).strip()
        self._api_url = str(
            api_url
            or getattr(settings, "GITHUB_API_URL", "https://api.github.com")
        ).rstrip("/")
        self._timeout_seconds = timeout_seconds or self._configured_timeout()
        self._transport = transport

    @staticmethod
    def _configured_timeout() -> int:
        raw = (os.environ.get("GITHUB_BOT_TIMEOUT_SECONDS") or "20").strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise GitHubFreshnessError(
                "GITHUB_BOT_TIMEOUT_SECONDS must be a whole number."
            ) from exc
        if not 1 <= value <= 120:
            raise GitHubFreshnessError(
                "GITHUB_BOT_TIMEOUT_SECONDS must be between 1 and 120."
            )
        return value

    def _headers(self, token: str | None = None) -> dict[str, str]:
        selected = str(token if token is not None else self._token).strip()
        if not selected:
            raise GitHubFreshnessError(
                "GITHUB_BOT_TOKEN is missing from the backend runtime environment."
            )
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {selected}",
            "User-Agent": "Veyra-Worker-Agent",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _safe_error(self, value: object) -> str:
        text = str(value or "").replace(self._token, "[REDACTED]").strip()
        return text[:600] + ("…" if len(text) > 600 else "")

    def _request(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response | None:
        try:
            response = client.get(f"{self._api_url}{path}", params=params)
        except httpx.TimeoutException as exc:
            raise GitHubFreshnessError("GitHub freshness check timed out.") from exc
        except httpx.HTTPError as exc:
            raise GitHubFreshnessError(
                f"GitHub freshness check failed: {self._safe_error(exc)}"
            ) from exc

        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code == 401:
            raise GitHubFreshnessError(
                "GitHub rejected the worker token during the freshness check."
            )
        if response.status_code == 403:
            raise GitHubFreshnessError(
                "GitHub denied the worker freshness check. Check token permissions and rate limits."
            )
        if response.status_code != 200:
            raise GitHubFreshnessError(
                f"GitHub returned HTTP {response.status_code} during the freshness check."
            )
        return response

    @staticmethod
    def _payload(response: httpx.Response, *, description: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubFreshnessError(
                f"GitHub returned invalid JSON for {description}."
            ) from exc

    @staticmethod
    def _issue_reference_pattern(issue_number: int) -> re.Pattern[str]:
        return re.compile(
            rf"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#{issue_number}\b"
        )

    @staticmethod
    def _branch_issue_pattern(issue_number: int) -> re.Pattern[str]:
        return re.compile(
            rf"(?i)(?:^|[-_/])issue[-_/]?{issue_number}(?:[-_/]|$)"
        )

    def _pull_references_issue(
        self,
        pull: dict[str, Any],
        *,
        owner: str,
        repository: str,
        issue_number: int,
    ) -> bool:
        body = str(pull.get("body") or "")
        issue_url = f"https://github.com/{owner}/{repository}/issues/{issue_number}"
        if issue_url.casefold() in body.casefold():
            return True
        if self._issue_reference_pattern(issue_number).search(body):
            return True
        branch = str((pull.get("head") or {}).get("ref") or "")
        return bool(self._branch_issue_pattern(issue_number).search(branch))

    @staticmethod
    def _pull_head_owner(pull: dict[str, Any]) -> str:
        head = pull.get("head") or {}
        repo_owner = ((head.get("repo") or {}).get("owner") or {}).get("login")
        user_login = (head.get("user") or {}).get("login")
        return str(repo_owner or user_login or "").strip()

    def _list_pulls(
        self,
        client: httpx.Client,
        *,
        owner: str,
        repository: str,
    ) -> list[dict[str, Any]]:
        pulls: list[dict[str, Any]] = []
        for page in range(1, 4):
            response = self._request(
                client,
                f"/repos/{owner}/{repository}/pulls",
                params={
                    "state": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            payload = self._payload(response, description="pull requests")
            if not isinstance(payload, list):
                raise GitHubFreshnessError(
                    "GitHub returned an invalid pull-request collection."
                )
            pulls.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 100:
                break
        return pulls

    def _list_branches(
        self,
        client: httpx.Client,
        *,
        owner: str,
        repository: str,
    ) -> list[str]:
        branches: list[str] = []
        for page in range(1, 4):
            response = self._request(
                client,
                f"/repos/{owner}/{repository}/branches",
                params={"per_page": 100, "page": page},
            )
            payload = self._payload(response, description="branches")
            if not isinstance(payload, list):
                raise GitHubFreshnessError(
                    "GitHub returned an invalid branch collection."
                )
            for item in payload:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        branches.append(name)
            if len(payload) < 100:
                break
        return branches

    def check(self, worker: WorkerAgent, job: VeyraJob) -> GitHubFreshnessResult:
        worker.refresh_from_db()
        job = VeyraJob.objects.select_related(
            "draft",
            "draft__github_repository_access__installation",
        ).get(pk=job.pk)

        owner = job.draft.repository_owner.strip()
        repository = job.draft.repository_name.strip()
        issue_number = int(job.draft.issue_number)
        issue_url = f"https://github.com/{owner}/{repository}/issues/{issue_number}"
        checked_at = timezone.now().isoformat()

        access = job.draft.github_repository_access
        app_mode = access is not None
        if app_mode:
            try:
                effective_token = token_for_repository(access).token
            except GitHubAppError as exc:
                raise GitHubFreshnessError(
                    f"The client repository installation is unavailable: {exc}"
                ) from exc
            expected_head_owner = owner
            branch_owner = owner
        else:
            if not worker.github_connected or not worker.github_username:
                raise GitHubFreshnessError(
                    "The legacy worker GitHub account is not connected."
                )
            effective_token = self._token
            expected_head_owner = worker.github_username
            branch_owner = worker.github_username

        with httpx.Client(
            headers=self._headers(effective_token),
            timeout=self._timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            issue_response = self._request(
                client,
                f"/repos/{owner}/{repository}/issues/{issue_number}",
                allow_not_found=True,
            )
            if issue_response is None:
                return GitHubFreshnessResult(
                    passed=False,
                    code="GITHUB_ISSUE_NOT_FOUND",
                    detail="GitHub no longer exposes the committed issue.",
                    issue_state="NOT_FOUND",
                    issue_url=issue_url,
                    checked_at=checked_at,
                )

            issue = self._payload(issue_response, description="repository issue")
            if not isinstance(issue, dict):
                raise GitHubFreshnessError("GitHub returned an invalid issue record.")
            authoritative_issue_url = str(issue.get("html_url") or issue_url).strip()
            if issue.get("pull_request"):
                return GitHubFreshnessResult(
                    passed=False,
                    code="GITHUB_TARGET_IS_PULL_REQUEST",
                    detail="The committed GitHub URL resolves to a pull request, not an issue.",
                    issue_state=str(issue.get("state") or "UNKNOWN").upper(),
                    issue_url=authoritative_issue_url,
                    checked_at=checked_at,
                )

            issue_state = str(issue.get("state") or "UNKNOWN").upper()
            if issue_state != "OPEN":
                return GitHubFreshnessResult(
                    passed=False,
                    code="GITHUB_ISSUE_CLOSED",
                    detail=f"GitHub reports the issue state as {issue_state}.",
                    issue_state=issue_state,
                    issue_url=authoritative_issue_url,
                    checked_at=checked_at,
                )

            for pull in self._list_pulls(client, owner=owner, repository=repository):
                if self._pull_head_owner(pull).casefold() != expected_head_owner.casefold():
                    continue
                if not self._pull_references_issue(
                    pull,
                    owner=owner,
                    repository=repository,
                    issue_number=issue_number,
                ):
                    continue
                pull_url = str(pull.get("html_url") or "").strip()
                merged = bool(pull.get("merged_at"))
                pull_state = "MERGED" if merged else str(pull.get("state") or "UNKNOWN").upper()
                if merged or pull_state == "OPEN":
                    return GitHubFreshnessResult(
                        passed=False,
                        code="GITHUB_WORKER_PR_MERGED" if merged else "GITHUB_WORKER_PR_OPEN",
                        detail=(
                            "Veyra already merged a pull request for this issue."
                            if merged
                            else "Veyra already has an open pull request for this issue."
                        ),
                        issue_state=issue_state,
                        issue_url=authoritative_issue_url,
                        existing_pull_request_url=pull_url,
                        existing_pull_request_state=pull_state,
                        checked_at=checked_at,
                    )

            branch_pattern = self._branch_issue_pattern(issue_number)
            if app_mode:
                branches = self._list_branches(client, owner=owner, repository=repository)
            else:
                fork_response = self._request(
                    client,
                    f"/repos/{worker.github_username}/{repository}",
                    allow_not_found=True,
                )
                branches = []
                if fork_response is not None:
                    fork = self._payload(fork_response, description="worker fork")
                    if not isinstance(fork, dict):
                        raise GitHubFreshnessError("GitHub returned an invalid fork record.")
                    source_name = f"{owner}/{repository}".casefold()
                    fork_full_name = str(fork.get("full_name") or "").casefold()
                    parent_name = str((fork.get("parent") or {}).get("full_name") or "").casefold()
                    source_owned_by_worker = source_name == fork_full_name
                    valid_fork = bool(fork.get("fork")) and parent_name == source_name
                    if not source_owned_by_worker and not valid_fork:
                        return GitHubFreshnessResult(
                            passed=False,
                            code="GITHUB_FORK_COLLISION",
                            detail="The worker account already has an unrelated repository with this name.",
                            issue_state=issue_state,
                            issue_url=authoritative_issue_url,
                            checked_at=checked_at,
                        )
                    branches = self._list_branches(
                        client,
                        owner=branch_owner,
                        repository=repository,
                    )

            for branch in branches:
                if branch.casefold().startswith("veyra/") and branch_pattern.search(branch):
                    return GitHubFreshnessResult(
                        passed=False,
                        code="GITHUB_WORKER_BRANCH_EXISTS",
                        detail="Veyra already has a branch for this issue.",
                        issue_state=issue_state,
                        issue_url=authoritative_issue_url,
                        existing_branch=branch,
                        checked_at=checked_at,
                    )

        return GitHubFreshnessResult(
            passed=True,
            code="GITHUB_FRESH",
            detail="The GitHub issue is open with no existing Veyra pull request or branch.",
            issue_state="OPEN",
            issue_url=issue_url,
            checked_at=checked_at,
        )
