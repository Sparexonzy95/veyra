"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/sidebar/theme-toggler";
import { MobileTrigger } from "@/components/layout/mobile-trigger";
import { Loader2, LogOut, RefreshCw, Wallet } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";

function titleFor(pathname: string) {
  if (pathname === "/dashboard/agents/new") return "Create Agent";
  if (/\/dashboard\/agents\/[^/]+/.test(pathname)) return "Agent Details";
  if (pathname.startsWith("/dashboard/agents")) return "My Agents";
  if (/\/dashboard\/jobs\/\d+/.test(pathname)) return "Job Details";
  if (pathname.startsWith("/dashboard/jobs")) return "Jobs";
  if (pathname.startsWith("/dashboard/profile")) return "Profile";
  return "Dashboard";
}

export function Header() {
  const pathname = usePathname();
  const { circleToken, refreshMe, logout } = useVeyra();
  const [loggingOut, setLoggingOut] = useState(false);
  async function refreshBalance() {
    if (!circleToken) {
      toast.error("Reconnect your secure wallet to refresh the balance.");
      return;
    }
    try {
      await apiFetch("/api/v1/client/wallet/balance/", { circleUserToken: circleToken });
      await refreshMe();
      toast.success("Wallet balance refreshed.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Balance refresh failed.");
    }
  }
  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
    }
  }
  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-4 sm:px-6 md:px-8">
        <MobileTrigger />
        <h2 className="text-xl font-bold tracking-tight md:text-2xl">{titleFor(pathname)}</h2>
        <div className="flex items-center gap-2 md:gap-4">
          <ThemeToggle />
          <Button variant="outline" size="default" onClick={() => void refreshBalance()} className="flex items-center gap-2">
            <Wallet className="h-4 w-4" />
            <span className="hidden sm:inline">Wallet</span>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="default"
            onClick={() => void handleLogout()}
            disabled={loggingOut}
            className="flex items-center gap-2"
            aria-label="Log out of Veyra"
            title="Log out"
          >
            {loggingOut ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <LogOut className="h-4 w-4" />
            )}
            <span className="hidden sm:inline">{loggingOut ? "Logging out…" : "Log out"}</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
