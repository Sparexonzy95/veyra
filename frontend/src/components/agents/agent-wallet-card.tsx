"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AgentSummary } from "@/types/veyra";
import { Check, Copy, ExternalLink, Loader2, ShieldCheck, Wallet } from "lucide-react";
import { toast } from "sonner";

const ARC_EXPLORER = "https://testnet.arcscan.app";

export function AgentWalletCard({
  agent,
}: {
  agent: AgentSummary;
  onRefresh: () => void | Promise<void>;
}) {
  const ready = Boolean(agent.worker_wallet_address);
  const creating = agent.provisioning_stage === "CREATING_WALLET";

  async function copyAddress() {
    if (!agent.worker_wallet_address) return;
    await navigator.clipboard.writeText(agent.worker_wallet_address);
    toast.success("Agent wallet address copied.");
  }

  return (
    <Card className={ready ? "border-emerald-500/30" : ""}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Wallet className="h-5 w-5" /> Dedicated Agent Wallet
            </CardTitle>
            <p className="mt-2 text-sm text-muted-foreground">
              Veyra creates this operational wallet automatically. It belongs only to {agent.name}{" "}
              and is never shared with the client workspace or another agent.
            </p>
          </div>
          <div
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
              ready
                ? "bg-emerald-500/10 text-emerald-600"
                : "bg-muted text-muted-foreground"
            }`}
          >
            {creating ? <Loader2 className="h-5 w-5 animate-spin" /> : ready ? <Check className="h-5 w-5" /> : <Wallet className="h-5 w-5" />}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {ready ? (
          <>
            <div className="rounded-xl border bg-muted/20 p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Agent operational address
              </p>
              <p className="mt-2 break-all font-mono text-sm">
                {agent.worker_wallet_address}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="outline" onClick={() => void copyAddress()}>
                  <Copy className="h-4 w-4" /> Copy
                </Button>
                <Button type="button" size="sm" variant="outline" asChild>
                  <a
                    href={`${ARC_EXPLORER}/address/${agent.worker_wallet_address}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink className="h-4 w-4" /> View on Arcscan
                  </a>
                </Button>
              </div>
            </div>
            <div className="grid gap-3 text-sm sm:grid-cols-2">
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">Network</p>
                <p className="mt-1 font-medium">{agent.wallet_blockchain}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">Control model</p>
                <p className="mt-1 font-medium">Circle developer-controlled SCA</p>
              </div>
            </div>
            <div className="flex items-start gap-2 rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-3 text-sm">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
              <p>
                Contract: {agent.contract_authorised ? "Authorised" : "Automatic authorisation in progress"}.
                This same wallet receives the agent&apos;s verified earnings.
              </p>
            </div>
          </>
        ) : (
          <div className="rounded-xl border bg-muted/20 p-4 text-sm">
            <p className="font-medium">{creating ? "Creating the dedicated wallet…" : "Wallet pending"}</p>
            <p className="mt-1 text-muted-foreground">
              No manual wallet address is required. Veyra creates one after the Agent Starter is connected.
              Use the retry action in the Agent Connection card if setup was interrupted.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
