"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { postJson } from "@/lib/api";
import type { AgentSummary } from "@/types/veyra";
import { CheckCircle2, CloudCog, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";

export function HostedRuntimeCard({
  agent,
  onRefresh,
}: {
  agent: AgentSummary;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const runtime = agent.runtime;
  const ready = runtime.runtime_mode === "VEYRA_HOSTED" && runtime.connected;

  async function prepareRuntime() {
    setBusy(true);
    setError(null);
    try {
      await postJson(`/api/v1/agents/${agent.id}/runtime/hosted/provision/`, {});
      await onRefresh();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The hosted runtime could not be prepared.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className={ready ? "border-emerald-500/30" : ""}>
      <CardHeader className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <CloudCog className="h-5 w-5" /> Hosted Runtime
          </CardTitle>
          <Badge variant={ready ? "success" : runtime.status === "UNHEALTHY" ? "destructive" : "outline"}>
            {ready ? "Ready" : runtime.status === "UNHEALTHY" ? "Needs attention" : "Preparing"}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Veyra automatically provides the secure environment where this agent runs. No download,
          pairing code, terminal, or always-on laptop is required.
        </p>
      </CardHeader>

      <CardContent className="space-y-5">
        {error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="grid gap-3 rounded-xl border p-4 text-sm sm:grid-cols-2">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Managed by</p>
            <p className="mt-1 font-medium">Veyra</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Start behaviour</p>
            <p className="mt-1 font-medium">Automatic when work arrives</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Environment</p>
            <p className="mt-1 font-medium">
              {[runtime.os_name, runtime.architecture].filter(Boolean).join(" · ") || "Veyra Cloud"}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Runtime version</p>
            <p className="mt-1 font-medium">{runtime.runner_version || "Hosted runtime"}</p>
          </div>
        </div>

        {ready ? (
          <div className="flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" />
            <div>
              <p className="font-medium">Runtime ready</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Veyra will start an isolated workspace when this agent receives a job and stop it
                after the work is complete.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3 rounded-xl border p-4">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 text-muted-foreground" />
              <div>
                <p className="font-medium">Veyra is preparing the runtime</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  This normally happens automatically. Use the button below only when the setup was interrupted.
                </p>
              </div>
            </div>
            <Button onClick={prepareRuntime} disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {busy ? "Preparing…" : "Prepare Hosted Runtime"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
