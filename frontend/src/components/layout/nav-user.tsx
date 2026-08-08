"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { profileHref } from "@/lib/profile-route";
import { Loader2, LogOut, User } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import type { WorkspaceKind } from "@/components/layout/app-sidebar";

/**
 * Account actions at the foot of the sidebar: Profile and Log out.
 *
 * The identity row above them is gone. It rendered an avatar with generated
 * initials and fell back to the literal text "Veyra user" whenever
 * `display_name` was empty — which is the common case, since nothing in the
 * product asks for one. That produced a fake identity: a placeholder name
 * beside initials derived from that placeholder, telling the user nothing
 * they did not already know. The signed-in account is shown on Profile, from
 * real data, which is one click away.
 *
 * Both rows are plain, always-visible controls rather than a dropdown, in
 * both workspaces and in the mobile drawer (which renders this same
 * sidebar), so signing out never depends on discovering a menu.
 */
export function NavUser({ workspace }: { workspace: WorkspaceKind }) {
  const { logout } = useVeyra();
  const pathname = usePathname();
  const [loggingOut, setLoggingOut] = useState(false);

  const href = profileHref(workspace);
  const onProfile = pathname === href;

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
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          asChild
          isActive={onProfile}
          tooltip="Profile"
          className="h-8 rounded-md text-sm text-sidebar-foreground/70 hover:text-sidebar-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-foreground"
        >
          <Link href={href}>
            <User className="h-4 w-4 shrink-0" />
            <span className="truncate">Profile</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>

      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip="Log out"
          onClick={() => void handleLogout()}
          aria-disabled={loggingOut}
          className="h-8 rounded-md text-sm text-sidebar-foreground/70 hover:text-sidebar-foreground"
        >
          {loggingOut ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />
          ) : (
            <LogOut className="h-4 w-4 shrink-0" />
          )}
          <span className="truncate">{loggingOut ? "Logging out…" : "Log out"}</span>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
