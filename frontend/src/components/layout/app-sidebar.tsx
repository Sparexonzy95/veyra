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
  Activity,
  Bot,
  BriefcaseBusiness,
  CircleDollarSign,
  Github,
  Home,
  ListChecks,
  Plus,
  Search,
  Settings,
  Trophy,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

export type WorkspaceKind = "client" | "agent-owner";

const icons = {
  activity: Activity,
  agents: Bot,
  assignments: ListChecks,
  available: Search,
  github: Github,
  home: Home,
  jobs: BriefcaseBusiness,
  payments: CircleDollarSign,
  plus: Plus,
  reputation: Trophy,
  settings: Settings,
};

export function AppSidebar({ workspace }: { workspace: WorkspaceKind }) {
  const pathname = usePathname();
  const { me } = useVeyra();
  const config = workspaceConfig[workspace];
  const dualRole = Boolean(
    me?.capabilities?.includes("CLIENT") &&
      me.capabilities.includes("AGENT_OWNER"),
  );

  return (
    <Sidebar collapsible="icon" className="border-r-border/70">
      <SidebarHeader className="space-y-3 p-3 group-data-[collapsible=icon]:p-2">
        <div className="flex w-full items-center justify-between">
          <Link href={config.home} className="flex items-center gap-2">
            <Image
              src="/veyra-logo.svg"
              alt="Veyra"
              width={42}
              height={42}
              className="rounded-md"
            />
            <span className="text-lg font-semibold group-data-[collapsible=icon]:hidden">
              Veyra
            </span>
          </Link>
          <SidebarTrigger className="h-10 w-10 group-data-[collapsible=icon]:hidden" />
        </div>
        <SidebarTrigger className="mx-auto hidden h-10 group-data-[collapsible=icon]:flex" />
        <div className="rounded-lg border bg-muted/30 p-1 group-data-[collapsible=icon]:hidden">
          {dualRole ? (
            <div className="grid grid-cols-2 gap-1" aria-label="Workspace switcher">
              <Link
                href="/client"
                className={`rounded-md px-2 py-2 text-center text-xs font-medium ${
                  workspace === "client" ? "bg-background shadow-sm" : "text-muted-foreground"
                }`}
              >
                Client
              </Link>
              <Link
                href="/agent-owner"
                className={`rounded-md px-2 py-2 text-center text-xs font-medium ${
                  workspace === "agent-owner" ? "bg-background shadow-sm" : "text-muted-foreground"
                }`}
              >
                Agent Owner
              </Link>
            </div>
          ) : (
            <p className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {config.label}
            </p>
          )}
        </div>
      </SidebarHeader>
      <SidebarContent className="px-2">
        <SidebarGroup>
          <SidebarGroupLabel>{config.label}</SidebarGroupLabel>
          <SidebarMenu>
            {config.navigation.map((item) => {
              const Icon = icons[item.icon as keyof typeof icons];
              const itemPath = item.url.split("?")[0];
              const active =
                itemPath === config.home
                  ? pathname === itemPath
                  : pathname.startsWith(itemPath);
              return (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild isActive={active} tooltip={item.title}>
                    <Link href={item.url} className="flex items-center gap-2">
                      <Icon className="h-4 w-4" />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <div className="flex flex-col gap-2 px-4 py-2 group-data-[collapsible=icon]:px-0">
          <Separator className="my-1" />
          <NavUser workspace={workspace} />
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
