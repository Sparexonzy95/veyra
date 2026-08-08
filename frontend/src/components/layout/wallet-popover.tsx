"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { apiFetch } from "@/lib/api";
import type { WorkspaceKind } from "@/components/layout/app-sidebar";
import {
  ArrowUpRight,
  Check,
  Copy,
  Loader2,
  RefreshCw,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

/**
 * Wallet summary for the authenticated top bar.
 *
 * Balance and address are read from `me.wallet`, which the Veyra provider
 * already holds — the popover issues no request of its own on open, so opening
 * and closing it repeatedly costs nothing. The one request it can make is the
 * explicit refresh, which reuses the same endpoint and `refreshMe()` the top
 * bar button used before.
 *
 * Dismissal, focus handling and Escape come from Radix rather than bespoke
 * listeners.
 */

/** Settlement destination per workspace. Both routes exist; neither is a stub. */
const settlementRoute: Record<WorkspaceKind, { href: string; label: string }> = {
  client: { href: "/client/payments", label: "View Payments" },
  "agent-owner": { href: "/agent-owner/earnings", label: "View Earnings" },
};

function shortenAddress(address: string) {
  if (!address) return "";
  // Enough leading characters to identify the wallet, enough trailing to
  // verify a pasted value, without wrapping on a narrow screen.
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function formatBalance(raw?: string | null) {
  const value = Number(raw ?? "");
  if (!Number.isFinite(value)) return raw ?? "0";
  return new Intl.NumberFormat("en", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function WalletPopover({ workspace }: { workspace: WorkspaceKind }) {
  const { me, circleToken, refreshMe } = useVeyra();
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState(false);

  const wallet = me?.wallet ?? null;
  const address = wallet?.address ?? "";

  // No wallet on this account: render nothing rather than an empty control.
  // Agent owners without an identity wallet fall into this branch, which is
  // why the trigger is gated on wallet data instead of on the workspace.
  if (!address) return null;

  const destination = settlementRoute[workspace];
  // The balance is absent only before the first sync has landed.
  const awaitingFirstBalance =
    wallet?.usdc_balance === undefined || wallet?.usdc_balance === null;

  async function refreshBalance() {
    if (refreshing) return;
    if (!circleToken) {
      setFailed(true);
      toast.error("Reconnect your secure wallet to refresh the balance.");
      return;
    }
    setRefreshing(true);
    setFailed(false);
    try {
      await apiFetch("/api/v1/client/wallet/balance/", {
        circleUserToken: circleToken,
      });
      await refreshMe();
    } catch (error) {
      setFailed(true);
      toast.error(
        error instanceof Error ? error.message : "Balance refresh failed.",
      );
    } finally {
      setRefreshing(false);
    }
  }

  async function copyAddress() {
    try {
      await navigator.clipboard.writeText(address);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("The address could not be copied.");
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          aria-label="Wallet balance and address"
        >
          <Wallet className="h-4 w-4" />
          <span className="hidden sm:inline">Wallet</span>
        </Button>
      </PopoverTrigger>

      {/* The portal renders outside the shell, so .veyra-scope is re-applied
          here or the popover would fall back to the root palette and lose the
          graphite surface and cream text. */}
      <PopoverContent
        className="veyra-scope w-[calc(100vw-2rem)] max-w-xs sm:w-72"
        collisionPadding={12}
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Balance
            </p>
            {refreshing && awaitingFirstBalance ? (
              <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading…
              </div>
            ) : (
              <p className="mt-0.5 text-xl font-semibold tracking-tight text-foreground">
                {formatBalance(wallet?.usdc_balance)}{" "}
                <span className="text-sm font-medium text-muted-foreground">
                  USDC
                </span>
              </p>
            )}
          </div>
          <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
            Arc Testnet
          </span>
        </div>

        <div className="mt-3 flex items-center justify-between gap-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5">
          <span className="truncate font-mono text-xs text-muted-foreground" title={address}>
            {shortenAddress(address)}
          </span>
          <button
            type="button"
            onClick={() => void copyAddress()}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={copied ? "Address copied" : "Copy wallet address"}
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-primary" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        </div>

        {failed ? (
          <p className="mt-2 text-xs text-muted-foreground">
            The balance could not be refreshed.
          </p>
        ) : null}

        <div className="mt-3 flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="flex-1 gap-1.5"
            onClick={() => void refreshBalance()}
            disabled={refreshing}
          >
            {refreshing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {failed ? "Retry" : "Refresh"}
          </Button>
          <Button asChild size="sm" className="flex-1 gap-1">
            <Link href={destination.href} onClick={() => setOpen(false)}>
              {destination.label}
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
