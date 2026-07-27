"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { postJson } from "@/lib/api";
import type { AgentSummary, AgentWalletProvisionResponse } from "@/types/veyra";
import { Check, Copy, ExternalLink, Loader2, ShieldCheck, Wallet } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const ARC_EXPLORER = "https://testnet.arcscan.app";

function shortAddress(value: string) {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "Not created";
}

export function AgentWalletCard({
  agent,
  onRefresh,
}: {
  agent: AgentSummary;
  onRefresh: () => void | Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const ready = Boolean(agent.worker_wallet_address);

  async function createWallet() {
    setCreating(true);
    try {
      const result = await postJson<AgentWalletProvisionResponse>(
        `/api/v1/agents/${agent.id}/create-wallet/`,
        {},
      );
      toast.success(
        result.wallet.created
          ? "Dedicated agent wallet created."
          : "This agent wallet was already ready.",
      );
      await onRefresh();
    } catch (walletError) {
      toast.error(
        walletError instanceof Error
          ? walletError.message
          : "The agent wallet could not be created.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function copyAddress() {
    if (!agent.worker_wallet_address) return;
    await navigator.clipboard.writeText(agent.worker_wallet_address);
    toast.success("Agent wallet address copied.");
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Wallet className="h-5 w-5" /> Dedicated Agent Wallet
            </CardTitle>
            <p className="mt-2 text-sm text-muted-foreground">
              This operational wallet belongs only to {agent.name}. It is separate
              from every client wallet and from wallets belonging to your other agents.
            </p>
          </div>
          <div
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
              ready
                ? "bg-emerald-500/10 text-emerald-600"
                : "bg-muted text-muted-foreground"
            }`}
          >
            {ready ? <Check className="h-5 w-5" /> : <Wallet className="h-5 w-5" />}
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
                Veyra uses this wallet only for this agent&apos;s contract claims,
                work submissions, reputation, and agent earnings.
              </p>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 text-sm">
              <p className="font-medium">No agent wallet yet</p>
              <p className="mt-1 text-muted-foreground">
                Veyra will create a new Arc Testnet SCA for this agent. Your client
                wallet will not be copied, linked, or reused.
              </p>
            </div>
            <Button type="button" onClick={() => void createWallet()} disabled={creating || !agent.runtime.connected}>
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wallet className="h-4 w-4" />}
              {creating ? "Creating wallet…" : "Create dedicated agent wallet"}
            </Button>
            {!agent.runtime.connected ? (
              <p className="text-xs text-muted-foreground">
                The hosted runtime must finish preparing before the wallet is created.
              </p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
