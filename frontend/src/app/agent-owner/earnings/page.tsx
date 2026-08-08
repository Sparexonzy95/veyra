"use client";

import { useOwnedAgents } from "@/components/agents/use-owned-agents";
import { PageHeader } from "@/components/dashboard/page-header";
import { Panel, PanelHeader } from "@/components/dashboard/panel";
import {
  DashboardPagination,
  PAGE_SIZE,
  pageCount,
  usePageParam,
} from "@/components/dashboard/pagination";
import { EmptyState } from "@/components/dashboard/states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch, postJson } from "@/lib/api";
import type { AgentSummary } from "@/types/veyra";
import { CircleDollarSign, ExternalLink, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

type Withdrawal = {
  id: string;
  amount_usdc: string;
  destination_address: string;
  status: "SUBMITTING" | "PENDING" | "COMPLETED" | "FAILED";
  circle_transaction_id: string;
  arc_transaction_hash: string;
  failure_message: string;
  created_at: string | null;
  completed_at: string | null;
};

type AgentWallet = {
  agent_id: string;
  agent_name: string;
  wallet_address: string;
  blockchain: string;
  symbol: "USDC";
  live_balance_usdc: string;
  lifetime_earned_usdc: string;
  withdrawn_usdc: string;
  operational_reserve_usdc: string;
  available_to_withdraw_usdc: string;
  owner_wallet_address: string;
  withdrawal_in_progress: boolean;
  latest_withdrawal: Withdrawal | null;
};

function shortAddress(value: string) {
  if (!value || value.length < 12) return value;
  return `${value.slice(0, 6)}…${value.slice(-6)}`;
}

export default function EarningsPage() {
  const arcExplorer =
    process.env.NEXT_PUBLIC_ARC_EXPLORER_URL?.replace(/\/$/, "") ||
    "https://testnet.arcscan.app";
  const { agents } = useOwnedAgents();
  const total = agents.reduce(
    (sum, agent) => sum + Number(agent.execution.reputation.total_earned_usdc || 0),
    0,
  );
  const { page, setPage } = usePageParam();
  const totalPages = pageCount(agents.length, PAGE_SIZE.table);
  const visible = agents.slice((page - 1) * PAGE_SIZE.table, page * PAGE_SIZE.table);
  const listRef = useRef<HTMLDivElement | null>(null);

  const [selected, setSelected] = useState<AgentSummary | null>(null);
  const [wallet, setWallet] = useState<AgentWallet | null>(null);
  const [destination, setDestination] = useState("");
  const [amount, setAmount] = useState("");
  const [loadingWallet, setLoadingWallet] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadWallet = useCallback(async (agent: AgentSummary, quiet = false) => {
    if (!quiet) setLoadingWallet(true);
    try {
      const response = await apiFetch<{ wallet: AgentWallet }>(
        `/api/v1/agents/${agent.id}/wallet/`,
      );
      setWallet(response.wallet);
      setError(null);
      if (!quiet) {
        setDestination(response.wallet.owner_wallet_address || "");
        setAmount(response.wallet.available_to_withdraw_usdc);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Agent wallet could not be loaded.");
    } finally {
      if (!quiet) setLoadingWallet(false);
    }
  }, []);

  const openWithdraw = useCallback(
    (agent: AgentSummary) => {
      setSelected(agent);
      setWallet(null);
      setDestination("");
      setAmount("");
      setError(null);
      void loadWallet(agent);
    },
    [loadWallet],
  );

  useEffect(() => {
    if (!selected || !wallet?.withdrawal_in_progress) return;
    const timer = window.setInterval(() => {
      void loadWallet(selected, true);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [selected, wallet?.withdrawal_in_progress, loadWallet]);

  async function submitWithdrawal() {
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await postJson<{ wallet: AgentWallet; withdrawal: Withdrawal }>(
        `/api/v1/agents/${selected.id}/withdraw/`,
        { destination_address: destination, amount_usdc: amount },
      );
      setWallet(response.wallet);
      await loadWallet(selected, true);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Withdrawal could not be submitted.");
    } finally {
      setSubmitting(false);
    }
  }

  const latest = wallet?.latest_withdrawal;
  const completed = latest?.status === "COMPLETED";
  const pending = wallet?.withdrawal_in_progress;

  return (
    <>
      <PageHeader
        title="Earnings"
        description={`${total.toFixed(2)} USDC earned across your agents, settled after independent verification.`}
      />

      <Panel className="overflow-hidden" ref={listRef}>
        <PanelHeader title="By agent" />
        {visible.length ? (
          <ul className="divide-y divide-border">
            {visible.map((agent) => (
              <li key={agent.id} className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{agent.name}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {agent.execution.reputation.completed_jobs} completed jobs · {shortAddress(agent.worker_wallet_address)}
                  </p>
                </div>
                <div className="flex w-full items-center justify-between gap-3 sm:w-auto sm:justify-end">
                  <p className="text-sm font-medium">
                    {agent.execution.reputation.total_earned_usdc} USDC
                  </p>
                  <Button size="sm" variant="outline" onClick={() => openWithdraw(agent)}>
                    Withdraw
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={CircleDollarSign}
            title="No earnings yet"
            description="Earnings appear here once verified work settles."
          />
        )}
        {agents.length ? (
          <DashboardPagination
            page={page}
            totalPages={totalPages}
            totalItems={agents.length}
            onPageChange={setPage}
            scrollTargetRef={listRef}
          />
        ) : null}
      </Panel>

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Withdraw USDC</DialogTitle>
            <DialogDescription>
              {selected ? `Move verified earnings from ${selected.name}'s Arc wallet.` : ""}
            </DialogDescription>
          </DialogHeader>

          {loadingWallet ? (
            <div className="flex min-h-44 items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : wallet ? (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 rounded-lg border p-4 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">Available</p>
                  <p className="mt-1 font-semibold">{wallet.available_to_withdraw_usdc} USDC</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Lifetime earned</p>
                  <p className="mt-1 font-semibold">{wallet.lifetime_earned_usdc} USDC</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Already withdrawn</p>
                  <p className="mt-1">{wallet.withdrawn_usdc} USDC</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Operational reserve</p>
                  <p className="mt-1">{wallet.operational_reserve_usdc} USDC</p>
                </div>
              </div>

              {latest && (pending || completed || latest.status === "FAILED") ? (
                <div className="rounded-lg border p-4 text-sm">
                  <p className="font-medium">
                    {pending ? "Withdrawal processing" : completed ? "Last withdrawal completed" : "Last withdrawal failed"}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {latest.amount_usdc} USDC → {shortAddress(latest.destination_address)}
                  </p>
                  {latest.arc_transaction_hash ? (
                    <a
                      href={`${arcExplorer}/tx/${latest.arc_transaction_hash}`}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-foreground underline-offset-4 hover:underline"
                    >
                      View Arc transaction <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  ) : null}
                  {latest.failure_message ? (
                    <p className="mt-2 text-sm text-destructive">{latest.failure_message}</p>
                  ) : null}
                </div>
              ) : null}

              {!pending ? (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="withdraw-destination">Destination wallet</Label>
                    <Input
                      id="withdraw-destination"
                      value={destination}
                      onChange={(event) => setDestination(event.target.value)}
                      placeholder="0x…"
                    />
                    <p className="text-xs text-muted-foreground">
                      Your linked Arc wallet is filled in automatically when available.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <Label htmlFor="withdraw-amount">Amount</Label>
                      <button
                        type="button"
                        className="text-xs font-medium text-foreground underline-offset-4 hover:underline"
                        onClick={() => setAmount(wallet.available_to_withdraw_usdc)}
                      >
                        Max
                      </button>
                    </div>
                    <Input
                      id="withdraw-amount"
                      inputMode="decimal"
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
                      placeholder="0.00"
                    />
                  </div>
                </>
              ) : null}

              {error ? <p className="text-sm text-destructive">{error}</p> : null}
            </div>
          ) : error ? (
            <p className="py-6 text-sm text-destructive">{error}</p>
          ) : null}

          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)}>
              Close
            </Button>
            {wallet && !pending ? (
              <Button
                disabled={submitting || Number(amount) <= 0 || !destination.trim()}
                onClick={() => void submitWithdrawal()}
              >
                {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Withdraw USDC
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
