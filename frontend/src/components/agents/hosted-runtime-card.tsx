"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { postJson } from "@/lib/api";
import type { AgentSummary } from "@/types/veyra";
import {
  CheckCircle2,
  KeyRound,
  Link2,
  Loader2,
  RefreshCw,
  ServerCog,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

export function HostedRuntimeCard({
  agent,
  onRefresh,
}: {
  agent: AgentSummary;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [connectionLink, setConnectionLink] = useState("");
  const runtime = agent.runtime;
  const ready = runtime.runtime_mode === "OWNER_HOSTED" && runtime.connected;
  const needsFreshLink = !runtime.paired || runtime.status === "REVOKED";
  const provisioningNeedsAttention =
    Boolean(agent.provisioning_error) || !agent.contract_authorised;
  const showSetupPanel = !ready || provisioningNeedsAttention;

  async function retryProvisioning() {
    setBusy(true);
    try {
      await postJson(`/api/v1/agents/${agent.id}/provision/`, {
        connection_link: connectionLink.trim(),
      });
      toast.success("Agent provisioning completed.");
      setConnectionLink("");
      await onRefresh();
    } catch (requestError) {
      toast.error(
        requestError instanceof Error
          ? requestError.message
          : "Agent provisioning could not be completed.",
      );
      await onRefresh();
    } finally {
      setBusy(false);
    }
  }

  async function disconnectAgent() {
    setBusy(true);
    try {
      await postJson(`/api/v1/agents/${agent.id}/runtime/disconnect/`, {});
      toast.success("Agent disconnected.");
      await onRefresh();
    } catch (requestError) {
      toast.error(
        requestError instanceof Error
          ? requestError.message
          : "Agent could not be disconnected.",
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
            <ServerCog className="h-5 w-5" /> Agent Connection
          </CardTitle>
          <Badge
            variant={
              ready
                ? "success"
                : runtime.status === "UNHEALTHY"
                  ? "destructive"
                  : "outline"
            }
          >
            {ready ? "Online" : runtime.status.replaceAll("_", " ").toLowerCase()}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Connect the Agent Starter without sharing your provider API key.
        </p>
      </CardHeader>

      <CardContent className="space-y-5">
        {ready ? (
          <div className="flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" />
            <div>
              <p className="font-medium">Secure connection active</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Last connected: {runtime.last_seen_at ? new Date(runtime.last_seen_at).toLocaleString() : "Just now"}.
              </p>
            </div>
          </div>
        ) : null}

        <details className="rounded-xl border bg-muted/20 p-4 text-sm">
          <summary className="cursor-pointer font-medium">Technical details</summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div><p className="text-xs text-muted-foreground">Provider</p><p className="mt-1 font-medium">{runtime.provider || "Not verified"}</p></div>
            <div><p className="text-xs text-muted-foreground">Model</p><p className="mt-1 font-medium">{runtime.model || "Not verified"}</p></div>
            <div><p className="text-xs text-muted-foreground">Agent version</p><p className="mt-1 font-medium">{runtime.runner_version || "Not connected"}</p></div>
            <div><p className="text-xs text-muted-foreground">Protocol</p><p className="mt-1 font-medium">{runtime.protocol_version || "Not connected"}</p></div>
          </div>
          {runtime.public_key_fingerprint ? (
            <p className="mt-4 break-all border-t pt-4 font-mono text-[11px] text-muted-foreground">
              Signing key: {runtime.public_key_fingerprint}
            </p>
          ) : null}
        </details>

        {showSetupPanel ? (
          <div className="space-y-4 rounded-xl border p-4">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 text-muted-foreground" />
              <div>
                <p className="font-medium">
                  {ready ? "Automatic setup needs attention" : "Connection or provisioning needs attention"}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {agent.provisioning_error ||
                    runtime.health_message ||
                    (ready
                      ? "The agent is online. Retry will reuse this connection and continue the remaining setup."
                      : "Paste a fresh connection link and retry.")}
                </p>
              </div>
            </div>

            {needsFreshLink ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Link2 className="h-4 w-4" /> Agent Starter connection URL
                </div>
                <Input
                  value={connectionLink}
                  onChange={(event) => setConnectionLink(event.target.value)}
                  placeholder="veyra-connect://localhost:9100/connect/..."
                  className="font-mono text-xs"
                />
              </div>
            ) : (
              <div className="flex items-start gap-2 rounded-lg bg-muted/40 p-3 text-sm text-muted-foreground">
                <KeyRound className="mt-0.5 h-4 w-4 shrink-0" />
                Agent ownership is already verified. Retrying will reuse the same connection and wallet.
              </div>
            )}

            <Button
              onClick={() => void retryProvisioning()}
              disabled={busy || (needsFreshLink && !connectionLink.trim())}
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {busy ? "Connecting Agent…" : needsFreshLink ? "Connect Agent" : "Retry automatic setup"}
            </Button>
          </div>
        ) : null}

        {ready ? (
          <Button
            variant="outline"
            onClick={() => void disconnectAgent()}
            disabled={busy}
          >
            Disconnect Agent
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
