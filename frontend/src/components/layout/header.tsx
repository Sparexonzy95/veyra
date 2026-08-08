"use client";

import { ThemeToggle } from "@/components/layout/sidebar/theme-toggler";
import { MobileTrigger } from "@/components/layout/mobile-trigger";
import { WalletPopover } from "@/components/layout/wallet-popover";
import type { WorkspaceKind } from "@/components/layout/app-sidebar";

export function Header({ workspace }: { workspace: WorkspaceKind }) {
  // The page title belongs to the shared PageHeader on each page, so the top
  // bar carries only navigation and wallet access.
  //
  // Log out used to live here as well as in the sidebar dropdown. It is now
  // one always-visible row in the sidebar footer, which is reachable on
  // mobile through the same drawer this trigger opens, so the duplicate has
  // been removed rather than kept "just in case".
  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/85 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-2 px-4 sm:px-6 md:px-8">
        <MobileTrigger />
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <ThemeToggle />
          {/* The top-bar wallet is the signed-in client's user-controlled
              wallet. Agent operational wallets are per-agent, so showing the
              client wallet inside the agent-owner workspace is misleading.
              Agent wallets live on their individual agent pages instead. */}
          {workspace === "client" ? <WalletPopover workspace={workspace} /> : null}
        </div>
      </div>
    </header>
  );
}
