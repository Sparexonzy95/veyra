"""Check the shape of the GitHub App installation URL without touching the database.

The project's test database cannot be created on every machine, but this part of
the flow is pure configuration handling, so it can be exercised directly:

    python backend/scripts/check_github_install_url.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import override_settings  # noqa: E402

from jobs.github_app import GitHubAppError, install_url  # noqa: E402

BASE = {
    "GITHUB_APP_ID": "123456",
    "GITHUB_APP_SLUG": "veyra-dev",
    "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nx\n-----END RSA PRIVATE KEY-----",
    "GITHUB_WEBHOOK_SECRET": "shhh",
    "GITHUB_APP_INSTALL_URL": "",
}

failures: list[str] = []


def expect_url(label: str, **overrides) -> None:
    with override_settings(**{**BASE, **overrides}):
        try:
            url = install_url(user_id="42", return_path="/client/github")
        except GitHubAppError as exc:
            failures.append(f"{label}: unexpected configuration error: {exc}")
            return
    prefix = "https://github.com/apps/veyra-dev/installations/new?state="
    if not url.startswith(prefix):
        failures.append(f"{label}: expected {prefix}..., got {url}")
        return
    if "/login/oauth/" in url:
        failures.append(f"{label}: built an OAuth URL: {url}")
        return
    print(f"  ok  {label}: {prefix}<signed-state>")


def expect_error(label: str, needle: str, **overrides) -> None:
    with override_settings(**{**BASE, **overrides}):
        try:
            url = install_url(user_id="42", return_path="/client/github")
        except GitHubAppError as exc:
            if needle.lower() not in str(exc).lower():
                failures.append(f"{label}: error did not mention {needle!r}: {exc}")
            else:
                print(f"  ok  {label}: rejected ({needle})")
            return
    failures.append(f"{label}: expected a configuration error, got {url}")


print("GitHub App installation URL")
expect_url("default slug-derived URL")
expect_url(
    "explicit install URL override",
    GITHUB_APP_INSTALL_URL="https://github.com/apps/veyra-dev/installations/new",
)
expect_error("missing slug", "GITHUB_APP_SLUG", GITHUB_APP_SLUG="")
expect_error(
    "OAuth authorize URL",
    "OAuth",
    GITHUB_APP_INSTALL_URL="https://github.com/login/oauth/authorize?client_id=abc",
)
expect_error(
    "non-installation URL",
    "/installations/new",
    GITHUB_APP_INSTALL_URL="https://github.com/apps/veyra-dev",
)

if failures:
    print("\nFAILED")
    for item in failures:
        print(f"  - {item}")
    raise SystemExit(1)
print("\nAll installation URL checks passed.")
