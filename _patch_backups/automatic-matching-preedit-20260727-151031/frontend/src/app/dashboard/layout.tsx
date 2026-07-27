"use client";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { Footer } from "@/components/layout/footer";
import { Header } from "@/components/layout/header";
import { useVeyra } from "@/components/providers/veyra-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { me, sdkReady } = useVeyra();
  const router = useRouter();
  useEffect(() => {
    if (sdkReady && me && !me.authenticated && !me.onboarding) router.replace("/login");
  }, [me, router, sdkReady]);
  if (!sdkReady || !me) {
    return <div className="flex min-h-svh items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  }
  const hasWorkspace = me.capabilities?.some((capability) =>
    capability === "CLIENT" || capability === "AGENT_OWNER",
  );
  if (!me.authenticated || !hasWorkspace) return null;
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <Header />
        <div className="min-h-screen flex flex-col">
          <main className="flex-1 space-y-4 p-4 pt-6 md:p-8">{children}</main>
          <Footer />
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
