from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from django.conf import settings

from jobs.github_app import GitHubAppError, token_for_repository
from jobs.models import GitHubRepositoryAccess, VeyraJob


class GitHubExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullRequestSnapshot:
    number: int
    html_url: str
    state: str
    merged: bool
    head_ref: str
    head_sha: str
    base_ref: str
    changed_files: tuple[str, ...]


class GitHubAppExecutionClient:
    """Repository-scoped GitHub App client for runtime delivery and verification."""

    def __init__(self, access: GitHubRepositoryAccess):
        self.access = access
        try:
            token = token_for_repository(access)
        except GitHubAppError as exc:
            raise GitHubExecutionError(str(exc)) from exc
        self.token = token.token
        self.expires_at = token.expires_at
        self.api_url = str(getattr(settings, "GITHUB_API_URL", "https://api.github.com")).rstrip("/")
        self.timeout = int(getattr(settings, "GITHUB_APP_TIMEOUT_SECONDS", 20))

    @classmethod
    def for_job(cls, job: VeyraJob) -> "GitHubAppExecutionClient":
        job = VeyraJob.objects.select_related(
            "draft__github_repository_access__installation"
        ).get(pk=job.pk)
        access = job.draft.github_repository_access
        if not access:
            raise GitHubExecutionError("The funded job has no GitHub App repository access.")
        if not access.active:
            raise GitHubExecutionError("The funded repository is no longer approved for Veyra.")
        return cls(access)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "Veyra-Execution-Layer",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...] = (200,),
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = httpx.request(
                method,
                f"{self.api_url}{path}",
                headers=self._headers(),
                json=json_payload,
                params=params,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GitHubExecutionError(f"GitHub request failed: {str(exc)[:300]}") from exc
        if response.status_code not in expected:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("message") or "")
            except Exception:
                pass
            raise GitHubExecutionError(
                f"GitHub returned HTTP {response.status_code}"
                + (f": {detail[:240]}" if detail else ".")
            )
        return response

    def pull_request(self, *, owner: str, repository: str, number: int) -> PullRequestSnapshot:
        safe_owner = quote(owner, safe="")
        safe_repo = quote(repository, safe="")
        payload = self.request(
            "GET", f"/repos/{safe_owner}/{safe_repo}/pulls/{int(number)}"
        ).json()
        if not isinstance(payload, dict):
            raise GitHubExecutionError("GitHub returned an invalid pull request.")
        changed: list[str] = []
        page = 1
        while page <= 10:
            values = self.request(
                "GET",
                f"/repos/{safe_owner}/{safe_repo}/pulls/{int(number)}/files",
                params={"per_page": 100, "page": page},
            ).json()
            if not isinstance(values, list):
                raise GitHubExecutionError("GitHub returned an invalid pull request file list.")
            for item in values:
                if isinstance(item, dict) and item.get("filename"):
                    changed.append(str(item["filename"]).replace("\\", "/"))
            if len(values) < 100:
                break
            page += 1
        head = payload.get("head") or {}
        base = payload.get("base") or {}
        return PullRequestSnapshot(
            number=int(payload.get("number") or number),
            html_url=str(payload.get("html_url") or ""),
            state=str(payload.get("state") or ""),
            merged=bool(payload.get("merged")),
            head_ref=str(head.get("ref") or ""),
            head_sha=str(head.get("sha") or "").lower(),
            base_ref=str(base.get("ref") or ""),
            changed_files=tuple(sorted(set(changed))),
        )

    def check_runs(self, *, owner: str, repository: str, commit_sha: str) -> list[dict[str, Any]]:
        safe_owner = quote(owner, safe="")
        safe_repo = quote(repository, safe="")
        response = self.request(
            "GET",
            f"/repos/{safe_owner}/{safe_repo}/commits/{quote(commit_sha, safe='')}/check-runs",
            expected=(200, 404),
            params={"per_page": 100},
        )
        if response.status_code == 404:
            return []
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        values = payload.get("check_runs") or []
        return [item for item in values if isinstance(item, dict)]
