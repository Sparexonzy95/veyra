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
import { Bot, BriefcaseBusiness, Home, User } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function AppSidebar() {
  const pathname = usePathname();
  const { me } = useVeyra();
  const capabilities = new Set(me?.capabilities ?? []);

  const items = [
    { title: "Dashboard", url: "/dashboard", icon: Home, visible: true },
    {
      title: "Client Jobs",
      url: "/dashboard/jobs",
      icon: BriefcaseBusiness,
      visible: capabilities.has("CLIENT"),
    },
    {
      title: "My Agents",
      url: "/dashboard/agents",
      icon: Bot,
      visible: capabilities.has("AGENT_OWNER"),
    },
    { title: "Profile", url: "/dashboard/profile", icon: User, visible: true },
  ].filter((item) => item.visible);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="p-3 group-data-[collapsible=icon]:p-2">
        <div className="flex w-full items-center justify-between">
          <div className="flex items-center gap-2">
            <Image
              src="/veyra-logo.svg"
              alt="Veyra"
              width={50}
              height={50}
              className="rounded-md"
            />
            <span className="text-lg font-semibold group-data-[collapsible=icon]:hidden">
              Veyra
            </span>
          </div>
          <SidebarTrigger className="h-10 w-10 self-end group-data-[collapsible=icon]:hidden" />
        </div>
        <SidebarTrigger className="mx-auto mt-2 hidden h-10 group-data-[collapsible=icon]:flex" />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Platform</SidebarGroupLabel>
          <SidebarMenu>
            {items.map((item) => {
              const active =
                item.url === "/dashboard"
                  ? pathname === item.url
                  : pathname.startsWith(item.url);
              return (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild isActive={active} tooltip={item.title}>
                    <Link href={item.url} className="flex items-center gap-2">
                      <item.icon className="h-4 w-4" />
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
          <NavUser />
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
