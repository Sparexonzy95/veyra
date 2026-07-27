"use client";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
export function MobileTrigger() {
  const { isMobile } = useSidebar();
  return isMobile ? <SidebarTrigger className="h-10 w-10 z-0" /> : null;
}
