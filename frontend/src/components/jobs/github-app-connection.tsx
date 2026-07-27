"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch, postJson } from "@/lib/api";
import type { GitHubConnectionStatus } from "@/types/veyra";
import { CheckCircle2, Github, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

export function GitHubAppConnection({
  compact = false,
  returnPath = "/dashboard/jobs",
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
      <div className="flex flex-col justify-between gap-3 rounded-lg border bg-emerald-500/5 p-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" />
          <div>
            <p className="font-medium">GitHub connected</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {status.installations.map((item) => item.account_login).join(", ")} · {status.repositories.length} approved {status.repositories.length === 1 ? "repository" : "repositories"}
            </p>
          </div>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => void refresh()} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </Button>
      </div>
      {!compact ? (
        <div className="flex flex-wrap gap-2">
          {status.repositories.map((repository) => (
            <Badge key={repository.id} variant="outline">
              {repository.full_name}{repository.private ? " · private" : ""}
            </Badge>
          ))}
        </div>
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

  if (compact) return content;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Github className="h-5 w-5" /> GitHub Repository Access
        </CardTitle>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}
