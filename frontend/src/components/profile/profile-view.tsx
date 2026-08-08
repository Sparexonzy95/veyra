"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { Panel } from "@/components/dashboard/panel";
import { EmptyState, ErrorState, LoadingRows } from "@/components/dashboard/states";
import { useVeyra } from "@/components/providers/veyra-provider";
import type { WorkspaceKind } from "@/components/layout/app-sidebar";
import { apiFetch } from "@/lib/api";
import type { GitHubConnectionStatus } from "@/types/veyra";
import { Check, Copy, UserCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

/**
 * The Profile page for both workspaces.
 *
 * One component rather than two near-copies, so Client and Agent Owner cannot
 * drift apart. What it shows is strictly what the application already knows
 * about the signed-in account, from `/api/v1/auth/me/` plus — for clients —
 * the GitHub App status that the GitHub page already uses.
 *
 * Deliberately absent, because none of it exists behind the API:
 *
 *   - notification and timezone preferences. `ClientProfile` stores these,
 *     but there is no endpoint to read or update them after onboarding, so a
 *     form here could not load or save. Showing one would be a promise the
 *     backend does not keep.
 *   - organisation name, for the same reason.
 *   - wallet balance, which the top-bar wallet popover owns. Repeating it
 *     gives two numbers that can disagree while one is mid-refresh.
 *   - a Log out button. It is a permanent row in the sidebar footer now.
 *
 * There is no Save button because there is no writable field. `MeView` is
 * read-only and `/api/v1/onboarding/...` only creates a profile, so every
 * value below is presented as text rather than as a disabled input.
 *
 * The wallet address is shown truncated with a Copy action: the full 42
 * characters are needed for a transfer but not for reading the page, and
 * spelling them out stretches the row across the viewport.
 */
export function ProfileView({ workspace }: { workspace: WorkspaceKind }) {
  const { me } = useVeyra();
  const [github, setGithub] = useState<GitHubConnectionStatus | null>(null);
  const [githubError, setGithubError] = useState<string | null>(null);

  // Only clients have a GitHub App installation; the endpoint is under
  // /api/v1/client/, so asking for it as an agent owner would be a 403.
  const canReadGithub = workspace === "client";

  const loadGithub = useCallback(async () => {
    if (!canReadGithub) return;
    try {
      setGithub(
        await apiFetch<GitHubConnectionStatus>(
          "/api/v1/client/github/app/status/",
        ),
      );
      setGithubError(null);
    } catch (error) {
      setGithubError(
        error instanceof Error
          ? error.message
          : "GitHub connection could not be checked.",
      );
    }
  }, [canReadGithub]);

  useEffect(() => {
    void loadGithub();
  }, [loadGithub]);

  const user = me?.user;
  const email = user?.email?.trim() ?? "";
  const wallet = me?.wallet ?? null;
  const capabilities = me?.capabilities ?? [];
  // account_login is the connected GitHub account, which is a real identity
  // rather than a field we ask the user to type.
  const githubLogin = github?.connected
    ? (github.installations[0]?.account_login ?? "")
    : "";

  const rows: { label: string; value: React.ReactNode }[] = [];
  if (user?.display_name?.trim()) {
    rows.push({ label: "Display name", value: user.display_name });
  }
  if (email) rows.push({ label: "Email", value: email });
  if (capabilities.length) {
    rows.push({ label: "Access", value: capabilities.map(readable).join(" · ") });
  }
  if (githubLogin) {
    rows.push({
      label: "GitHub",
      value: (
        <span className="inline-flex items-center gap-2">
          {githubLogin}
          <Link
            href="/client/github"
            className="text-xs font-normal text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            Manage
          </Link>
        </span>
      ),
    });
  }
  // `me.wallet` is the user's client/identity wallet. Agent owners can own
  // multiple agents, each with a different developer-controlled wallet, so
  // never present the account wallet as if it belonged to an agent workspace.
  if (workspace === "client" && wallet?.address) {
    rows.push({
      label: "Wallet",
      value: <WalletValue address={wallet.address} />,
    });
  }
  if (workspace === "client" && wallet?.blockchain) {
    rows.push({ label: "Network", value: wallet.blockchain });
  }

  return (
    <>
      <PageHeader title="Profile" description="Your Veyra account details." />

      {githubError ? (
        <ErrorState message={githubError} onRetry={() => void loadGithub()} />
      ) : null}

      {/* No "Account" header strip: the page title already says whose
          details these are, so the strip was a label for a label. */}
      <Panel className="overflow-hidden">
        {!me ? (
          <LoadingRows rows={3} />
        ) : rows.length ? (
          <dl className="divide-y divide-border">
            {rows.map((row) => (
              <div
                key={row.label}
                className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-6"
              >
                <dt className="text-sm text-muted-foreground">{row.label}</dt>
                <dd className="min-w-0 break-words text-sm font-medium sm:text-right">
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <EmptyState
            icon={UserCircle}
            title="No profile details available yet"
          />
        )}
      </Panel>
    </>
  );
}

/** Truncated address plus a Copy action, so the full value stays reachable. */
function WalletValue({ address }: { address: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(address);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be denied; the title attribute still carries
      // the full address so the value is never trapped in the UI.
      toast.error("Could not copy the address.");
    }
  }

  return (
    <span className="inline-flex items-center gap-2 sm:justify-end">
      <span className="font-mono text-xs" title={address}>
        {`${address.slice(0, 6)}…${address.slice(-4)}`}
      </span>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label="Copy wallet address"
        className="text-muted-foreground transition-colors hover:text-foreground"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-primary" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
    </span>
  );
}

/** Capability codes as the UI names them elsewhere. */
function readable(code: string) {
  if (code === "CLIENT") return "Client";
  if (code === "AGENT_OWNER") return "Agent owner";
  return code;
}
