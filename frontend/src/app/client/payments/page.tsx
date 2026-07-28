"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import type { CircleTransactionStatus, WalletSummary } from "@/types/veyra";
import { CircleDollarSign, ReceiptText } from "lucide-react";
import { useEffect, useState } from "react";

export default function ClientPaymentsPage() {
  const [wallet, setWallet] = useState<WalletSummary | null>(null);
  const [transactions, setTransactions] = useState<CircleTransactionStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      apiFetch<WalletSummary>("/api/v1/client/wallet/"),
      apiFetch<{ results: CircleTransactionStatus[] }>("/api/v1/client/transactions/"),
    ]).then(([nextWallet, page]) => {
      setWallet(nextWallet);
      setTransactions(page.results);
    }).catch((loadError) => setError(loadError instanceof Error ? loadError.message : "Payments could not be loaded."));
  }, []);

  return (
    <div className="space-y-6">
      <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Client workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Payments</h1><p className="mt-1.5 text-sm text-muted-foreground">Your wallet, approvals, escrow funding and refunds.</p></div>
      {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div> : null}
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><CircleDollarSign className="h-5 w-5" /> Wallet balance</CardTitle></CardHeader><CardContent><p className="text-3xl font-bold">{wallet?.usdc_balance ?? "0"} USDC</p><p className="mt-1 text-sm text-muted-foreground">{wallet?.blockchain ?? "Arc Testnet"}</p></CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ReceiptText className="h-5 w-5" /> Payment activity</CardTitle></CardHeader><CardContent className="divide-y p-0">{transactions.length ? transactions.map((transaction) => <div key={transaction.id} className="flex items-center justify-between gap-4 p-4"><div><p className="text-sm font-medium">{transaction.purpose.replaceAll("_", " ")}</p><p className="text-xs text-muted-foreground">{new Date(transaction.created_at).toLocaleString()}</p></div><span className="text-sm font-medium">{transaction.status.replaceAll("_", " ").toLowerCase()}</span></div>) : <p className="p-6 text-sm text-muted-foreground">No payment activity yet.</p>}</CardContent></Card>
    </div>
  );
}
