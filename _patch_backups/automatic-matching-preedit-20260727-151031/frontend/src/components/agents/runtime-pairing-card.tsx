"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { postJson } from "@/lib/api";
import type { AgentSummary, RuntimePairingCodeResponse } from "@/types/veyra";
import {
  Check,
  Clock3,
  Copy,
  Laptop,
  Radio,
  RefreshCw,
  ShieldOff,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

function formatLastSeen(value: string | null) {
  if (!value) return "No heartbeat received";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 10) return "Just now";
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

function runtimeLabel(status: AgentSummary["runtime"]["status"]) {
  return status.replaceAll("_", " ").toLowerCase().replace(/^./, (value) => value.toUpperCase());
}

function runtimeVariant(status: AgentSummary["runtime"]["status"]) {
  if (status === "ONLINE") return "success" as const;
  if (status === "UNHEALTHY") return "destructive" as const;
  if (status === "OFFLINE" || status === "REVOKED") return "secondary" as const;
  return "outline" as const;
}

export function RuntimePairingCard({
  agent,
  onRefresh,
}: {
  agent: AgentSummary;
  onRefresh: () => Promise<void>;
}) {
  const [pairing, setPairing] = useState<RuntimePairingCodeResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (agent.runtime.connected && pairing) setPairing(null);
  }, [agent.runtime.connected, pairing]);

  const remaining = useMemo(() => {
    if (!pairing) return 0;
    return Math.max(0, Math.floor((new Date(pairing.expires_at).getTime() - now) / 1000));
  }, [now, pairing]);

  async function generateCode() {
    setBusy(true);
    setError(null);
    try {
      const response = await postJson<RuntimePairingCodeResponse>(
        `/api/v1/agents/${agent.id}/runtime/pairing-code/`,
        {},
      );
      setPairing(response);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Pairing code could not be created.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    setBusy(true);
    setError(null);
    try {
      await postJson(`/api/v1/agents/${agent.id}/runtime/revoke/`, {});
      setPairing(null);
      await onRefresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Runtime access could not be revoked.");
    } finally {
      setBusy(false);
    }
  }

  async function copyCode() {
    if (!pairing) return;
    await navigator.clipboard.writeText(pairing.pairing_code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  const runtime = agent.runtime;
  const hasActiveBinding = runtime.paired && runtime.status !== "REVOKED";

  return (
    <Card className={runtime.status === "ONLINE" ? "border-emerald-500/30" : ""}>
      <CardHeader className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <Radio className="h-5 w-5" /> External Runtime
          </CardTitle>
          <Badge variant={runtimeVariant(runtime.status)}>{runtimeLabel(runtime.status)}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Securely link the machine or server where this agent runs. Veyra never receives the model API key.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        {error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        {pairing && remaining > 0 ? (
          <div className="space-y-4 rounded-xl border border-primary/30 bg-primary/5 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-medium">One-time pairing code</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Open Veyra Runner, choose <strong>Pair Agent</strong>, and enter this code.
                </p>
              </div>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Clock3 className="h-3.5 w-3.5" />
                {Math.floor(remaining / 60).toString().padStart(2, "0")}:
                {(remaining % 60).toString().padStart(2, "0")}
              </div>
            </div>
            <button
              type="button"
              onClick={copyCode}
              className="flex w-full items-center justify-between rounded-xl border bg-background px-5 py-4 text-left"
            >
              <span className="font-mono text-xl font-semibold tracking-[0.18em]">{pairing.pairing_code}</span>
              {copied ? <Check className="h-5 w-5 text-emerald-600" /> : <Copy className="h-5 w-5 text-muted-foreground" />}
            </button>
            <p className="text-xs text-muted-foreground">
              The code works once and expires automatically. The Runner creates its device key locally; the private key never leaves that machine.
            </p>
          </div>
        ) : pairing ? (
          <div className="rounded-xl border p-4 text-sm text-muted-foreground">
            This pairing code expired. Generate a new one to continue.
          </div>
        ) : null}

        {runtime.status !== "NOT_CONNECTED" && runtime.status !== "REVOKED" ? (
          <div className="grid gap-3 rounded-xl border p-4 text-sm sm:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Runner</p>
              <p className="mt-1 font-medium">{runtime.runner_name || "Paired Runner"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Last seen</p>
              <p className="mt-1 font-medium">{formatLastSeen(runtime.last_seen_at)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Environment</p>
              <p className="mt-1 font-medium">
                {[runtime.os_name, runtime.architecture].filter(Boolean).join(" · ") || "Waiting for heartbeat"}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Runner version</p>
              <p className="mt-1 font-medium">{runtime.runner_version || "Waiting for heartbeat"}</p>
            </div>
          </div>
        ) : null}

        {runtime.status === "ONLINE" ? (
          <div className="flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
            <Wifi className="mt-0.5 h-5 w-5 text-emerald-600" />
            <div>
              <p className="font-medium">Runtime is online</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Veyra can securely reach this agent. The next onboarding step is GitHub App connection.
              </p>
            </div>
          </div>
        ) : runtime.status === "OFFLINE" ? (
          <div className="flex items-start gap-3 rounded-xl border p-4">
            <WifiOff className="mt-0.5 h-5 w-5 text-muted-foreground" />
            <div>
              <p className="font-medium">Runtime is offline</p>
              <p className="mt-1 text-sm text-muted-foreground">Start Veyra Runner on the paired machine. New job claims remain paused.</p>
            </div>
          </div>
        ) : runtime.status === "UNHEALTHY" ? (
          <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4">
            <Laptop className="mt-0.5 h-5 w-5 text-destructive" />
            <div>
              <p className="font-medium">Runner needs attention</p>
              <p className="mt-1 text-sm text-muted-foreground">{runtime.health_message || "The Runner reported an unhealthy environment."}</p>
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-3">
          <Button onClick={generateCode} disabled={busy}>
            {hasActiveBinding ? <RefreshCw className="h-4 w-4" /> : <Radio className="h-4 w-4" />}
            {busy ? "Working…" : hasActiveBinding ? "Pair Another Runner" : "Connect Runtime"}
          </Button>
          {hasActiveBinding ? (
            <Button variant="outline" onClick={revoke} disabled={busy}>
              <ShieldOff className="h-4 w-4" /> Revoke Runtime
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
