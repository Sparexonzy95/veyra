"use client";

import { NavUser } from "@/components/layout/nav-user";
import { useVeyra } from "@/components/providers/veyra-provider";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import workspaceConfig from "@/config/workspaces.json";
import {
  Bot,
  BriefcaseBusiness,
  CircleDollarSign,
  Github,
  Home,
  Plus,
  Settings,
} from "lucide-react";
import { VeyraWordmark } from "@/components/landing/veyra-wordmark";
import { resolveActiveNavIndex } from "@/lib/nav-active";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useMemo } from "react";

export type WorkspaceKind = "client" | "agent-owner";

const icons = {
  agents: Bot,
  github: Github,
  home: Home,
  jobs: BriefcaseBusiness,
  payments: CircleDollarSign,
  plus: Plus,
  settings: Settings,
};

export function AppSidebar({ workspace }: { workspace: WorkspaceKind }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { me } = useVeyra();
  const config = workspaceConfig[workspace];
  // Pick one winner across the whole list. `config.home` is passed so Overview
  // matches only itself instead of becoming a fallback for every workspace URL.
  const activeIndex = useMemo(
    () =>
      resolveActiveNavIndex(
        config.navigation,
        pathname,
        searchParams,
        config.home,
      ),
    [config.home, config.navigation, pathname, searchParams],
  );
  const dualRole = Boolean(
    me?.capabilities?.includes("CLIENT") &&
      me.capabilities.includes("AGENT_OWNER"),
  );

  return (
    <Sidebar collapsible="icon" className="veyra-scope border-r-border">
      <SidebarHeader className="space-y-3 p-3 group-data-[collapsible=icon]:p-2">
        <div className="flex w-full items-center justify-between">
          {/* The approved wordmark artwork, rendered through the same
              component the landing header uses. Previously this was a
              re-drawn text-only SVG, which meant the authenticated logo was
              a lookalike rather than the brand asset. */}
          <Link
            href={config.home}
            className="flex items-center group-data-[collapsible=icon]:hidden"
            aria-label="Veyra home"
          >
            <VeyraWordmark
              uid="sidebar"
              color="var(--veyra-cream)"
              className="w-[68px]"
            />
          </Link>
          <SidebarTrigger className="h-8 w-8 group-data-[collapsible=icon]:hidden" />
        </div>
        <SidebarTrigger className="mx-auto hidden h-8 group-data-[collapsible=icon]:flex" />
        <div className="rounded-md border border-border bg-muted/30 p-1 group-data-[collapsible=icon]:hidden">
          {dualRole ? (
            <div className="grid grid-cols-2 gap-1" aria-label="Workspace switcher">
              <Link
                href="/client"
                className={`rounded px-2 py-1.5 text-center text-xs font-medium transition-colors ${
                  workspace === "client"
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Client
              </Link>
              <Link
                href="/agent-owner"
                className={`rounded px-2 py-1.5 text-center text-xs font-medium transition-colors ${
                  workspace === "agent-owner"
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Agent Owner
              </Link>
            </div>
          ) : (
            <p className="px-2 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {config.label}
            </p>
          )}
        </div>
      </SidebarHeader>
      <SidebarContent className="px-2">
        <SidebarGroup>
          <SidebarGroupLabel className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {config.label}
          </SidebarGroupLabel>
          <SidebarMenu>
            {config.navigation.map((item, index) => {
              const Icon = icons[item.icon as keyof typeof icons];
              const active = index === activeIndex;
              return (
                <SidebarMenuItem key={item.title}>
                  {/* One nav treatment for both workspaces: same height, icon
                      size and radius. Active state is a graphite fill plus a
                      sand indicator rail, never a bright filled block. */}
                  <SidebarMenuButton
                    asChild
                    isActive={active}
                    tooltip={item.title}
                    className="relative h-9 rounded-md text-sm font-medium data-[active=true]:bg-accent data-[active=true]:text-foreground"
                  >
                    <Link href={item.url} className="flex items-center gap-2.5">
                      {active ? (
                        <span
                          aria-hidden
                          className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary"
                        />
                      ) : null}
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="truncate">{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      {/* Compact: one rule, then the three account rows. The old px-4/py-2
          wrapper indented the footer out of line with the nav above it. */}
      <SidebarFooter className="px-2 pb-2">
        <Separator className="mb-1" />
        <NavUser workspace={workspace} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
