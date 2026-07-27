"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { GitHubAppConnection } from "@/components/jobs/github-app-connection";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { apiFetch } from "@/lib/api";
import type { WalletSummary } from "@/types/veyra";
import { Check, Copy, Loader2, RefreshCw, ShieldCheck, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

export default function ProfilePage() {
  const { me, circleToken } = useVeyra();
  const [wallet, setWallet] = useState<WalletSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  async function loadWallet() {
    setLoading(true);
    try {
      setWallet(await apiFetch<WalletSummary>("/api/v1/client/wallet/"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Wallet could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadWallet(); }, []);

  async function refreshBalance() {
    if (!circleToken) {
      toast.error("Reconnect your secure wallet to refresh the balance.");
      return;
    }
    try {
      const result = await apiFetch<{ balance: string }>("/api/v1/client/wallet/balance/", { circleUserToken: circleToken });
      setWallet((current) => current ? { ...current, usdc_balance: result.balance } : current);
      toast.success("Balance refreshed.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Balance refresh failed.");
    }
  }

  async function copyAddress() {
    if (!wallet?.address) return;
    await navigator.clipboard.writeText(wallet.address);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold tracking-tight">Profile</h1><p className="text-muted-foreground">Your Veyra account and Circle wallet.</p></div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Account</CardTitle></CardHeader>
          <CardContent className="grid gap-4">
            <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Display name</p><p className="mt-1 font-medium">{me?.user?.display_name || "Veyra Client"}</p></div>
            <Separator />
            <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Email</p><p className="mt-1 font-medium">{me?.user?.email || "Not provided"}</p></div>
            <Separator />
            <div><p className="text-xs uppercase tracking-wide text-muted-foreground">Capability</p><p className="mt-1 font-medium">Post Jobs</p></div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle>Circle Wallet</CardTitle><Button variant="outline" size="sm" onClick={() => void refreshBalance()}><RefreshCw className="h-4 w-4" /> Refresh</Button></CardHeader>
          <CardContent>
            {loading ? <div className="flex items-center justify-center py-12"><Loader2 className="h-5 w-5 animate-spin text-primary" /></div> : wallet ? (
              <div className="grid gap-4">
                <div className="flex items-start gap-3 rounded-lg border bg-muted/20 p-4"><div className="rounded-full bg-primary-50 p-3 text-primary-700"><Wallet className="h-5 w-5" /></div><div className="min-w-0 flex-1"><p className="font-medium">{wallet.blockchain}</p><button type="button" onClick={() => void copyAddress()} className="mt-1 flex max-w-full items-center gap-2 font-mono text-xs text-muted-foreground hover:text-primary"><span className="truncate">{wallet.address}</span>{copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}</button></div></div>
                <div className="grid gap-4 md:grid-cols-2"><div className="rounded-lg border p-4"><p className="text-xs text-muted-foreground">USDC Balance</p><p className="mt-1 text-xl font-bold">{wallet.usdc_balance ?? "0"} USDC</p></div><div className="rounded-lg border p-4"><p className="text-xs text-muted-foreground">Wallet type</p><p className="mt-1 font-semibold">{wallet.account_type ?? "SCA"}</p></div></div>
                <div className="flex items-start gap-3 rounded-lg border p-4"><ShieldCheck className="mt-0.5 h-5 w-5 text-primary" /><p className="text-sm text-muted-foreground">This wallet is user-controlled. Veyra cannot spend funds without your Circle confirmation.</p></div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
      <GitHubAppConnection returnPath="/dashboard/profile" />
    </div>
  );
}
