"use client";

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
import { BriefcaseBusiness, Home, User } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NavUser } from "@/components/layout/nav-user";

const items = [
  { title: "Dashboard", url: "/dashboard", icon: Home },
  { title: "Jobs", url: "/dashboard/jobs", icon: BriefcaseBusiness },
  { title: "Profile", url: "/dashboard/profile", icon: User },
];

export function AppSidebar() {
  const pathname = usePathname();
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="p-3 group-data-[collapsible=icon]:p-2">
        <div className="flex w-full items-center justify-between">
          <div className="flex items-center gap-2">
            <Image src="/veyra-logo.svg" alt="Veyra" width={50} height={50} className="rounded-md" />
            <span className="text-lg font-semibold group-data-[collapsible=icon]:hidden">Veyra</span>
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
              const active = item.url === "/dashboard" ? pathname === item.url : pathname.startsWith(item.url);
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
