"use client";

import { Button } from "@/components/ui/button";
import { apiFetch, postJson } from "@/lib/api";
import {
  extractInstallState,
  isGitHubInstallUrl,
  rememberInstallState,
} from "@/lib/github-install";
import type { GitHubConnectionStatus } from "@/types/veyra";
import {
  ExternalLink,
  Github,
  Loader2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

/**
 * GitHub App connection status and repository access.
 *
 * The connected state is one status row plus a plain list of approved
 * repositories. It used to be a Card titled "GitHub Repository Access"
 * wrapping a tinted panel wrapping a badge cloud - three nested containers
 * around two facts, on a page whose own header already says "GitHub".
 *
 * `compact` is what the job builder renders: status row only, no
 * repository list, since the builder has its own repository picker.
 */
export function GitHubAppConnection({
  compact = false,
  returnPath = "/client/github",
  onStatusChange,
}: {
  compact?: boolean;
  returnPath?: string;
  onStatusChange?: (status: GitHubConnectionStatus | null) => void;
}) {
  const [status, setStatus] = useState<GitHubConnectionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) setLoading(true);
    try {
      const result = await apiFetch<GitHubConnectionStatus>(
        "/api/v1/client/github/app/status/",
      );
      setStatus(result);
      onStatusChange?.(result);
    } catch (error) {
      if (!silent) {
        toast.error(error instanceof Error ? error.message : "GitHub status could not be loaded.");
        setStatus(null);
        onStatusChange?.(null);
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [onStatusChange]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load({ silent: true });
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function connect() {
    setBusy(true);
    try {
      const result = await postJson<{ install_url: string }>(
        "/api/v1/client/github/app/install/start/",
        { return_path: returnPath },
      );

      // The browser must go to GitHub's installation screens. If the server
      // handed back anything else - an OAuth authorisation URL, or a relative
      // path that would land straight back on our own callback - navigating
      // would produce a callback with no installation parameters and look like
      // GitHub misbehaved. Fail loudly here instead.
      if (!isGitHubInstallUrl(result.install_url)) {
        toast.error(
          "Veyra's GitHub App installation URL is misconfigured on the server. Check GITHUB_APP_SLUG and GITHUB_APP_INSTALL_URL.",
        );
        setBusy(false);
        return;
      }

      // Keep a copy of the signed state for the round trip: GitHub echoes it
      // back on most paths through the install screens, but not all of them,
      // and losing it would otherwise strand a completed installation.
      rememberInstallState(extractInstallState(result.install_url), returnPath);
      window.location.assign(result.install_url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "GitHub connection could not start.");
      setBusy(false);
    }
  }

  async function refresh() {
    const installation = status?.installations[0];
    if (!installation) {
      await load();
      return;
    }
    setBusy(true);
    try {
      await postJson(
        `/api/v1/client/github/app/installations/${installation.id}/refresh/`,
        {},
      );
      await load();
      toast.success("GitHub access refreshed.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "GitHub access could not be refreshed.");
    } finally {
      setBusy(false);
    }
  }

  // GitHub's own settings screen for this installation. Organisation and
  // personal installations live under different paths, and without the
  // account type we cannot guess correctly - so the link only appears when
  // the data supports it rather than sending anyone to a 404.
  const installation = status?.installations[0];
  const manageUrl = installation
    ? installation.account_type?.toUpperCase() === "ORGANIZATION"
      ? `https://github.com/organizations/${installation.account_login}/settings/installations/${installation.installation_id}`
      : `https://github.com/settings/installations/${installation.installation_id}`
    : "";

  const content = loading ? (
    <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> Checking GitHub access…
    </div>
  ) : !status?.configured ? (
    <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
      <ShieldAlert className="mt-0.5 h-5 w-5 text-amber-600" />
      <div>
        <p className="font-medium">GitHub App setup is incomplete</p>
        <p className="mt-1 text-sm text-muted-foreground">
          The Veyra server needs its GitHub App ID, slug, private key and webhook secret.
        </p>
      </div>
    </div>
  ) : status.connected ? (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm">
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full bg-emerald-500"
        />
        <span className="font-medium">Connected</span>
        <span className="text-muted-foreground">
          {status.installations.map((item) => item.account_login).join(", ")} ·{" "}
          {status.repositories.length}{" "}
          {status.repositories.length === 1 ? "repository" : "repositories"}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => void refresh()}
            disabled={busy}
          >
            {busy ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
            )}
            Refresh
          </Button>
          {manageUrl ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              asChild
            >
              <a href={manageUrl} target="_blank" rel="noreferrer">
                Manage on GitHub
                <ExternalLink className="ml-1 h-3 w-3" />
              </a>
            </Button>
          ) : null}
        </div>
      </div>

      {!compact ? (
        status.repositories.length ? (
          <ul className="divide-y divide-border rounded-lg border border-border bg-card">
            {status.repositories.map((repository) => (
              <li
                key={repository.id}
                className="flex items-center justify-between gap-3 px-4 py-2 text-sm"
              >
                <a
                  href={repository.html_url}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate hover:underline"
                >
                  {repository.full_name}
                </a>
                {repository.private ? (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    Private
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-1 text-sm text-muted-foreground">
            No repositories approved yet.
          </p>
        )
      ) : null}
    </div>
  ) : (
    <div className="flex flex-col justify-between gap-4 rounded-lg border p-4 sm:flex-row sm:items-center">
      <div>
        <p className="font-medium">Connect the repository owner</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Install the Veyra GitHub App and choose only the repositories Veyra may use for jobs.
        </p>
      </div>
      <Button type="button" onClick={() => void connect()} disabled={busy}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Github className="h-4 w-4" />}
        Connect GitHub
      </Button>
    </div>
  );

  // No Card wrapper: on /client/github the page header already names the
  // section, and in the builder the step does.
  return content;
}
