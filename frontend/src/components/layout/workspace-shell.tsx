"use client";

import { AppSidebar, type WorkspaceKind } from "@/components/layout/app-sidebar";
import { Footer } from "@/components/layout/footer";
import { Header } from "@/components/layout/header";
import { useVeyra } from "@/components/providers/veyra-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

const capabilityFor: Record<WorkspaceKind, "CLIENT" | "AGENT_OWNER"> = {
  client: "CLIENT",
  "agent-owner": "AGENT_OWNER",
};

export function WorkspaceShell({
  workspace,
  children,
}: {
  workspace: WorkspaceKind;
  children: React.ReactNode;
}) {
  const { me, sdkReady } = useVeyra();
  const router = useRouter();
  const allowed = Boolean(me?.capabilities?.includes(capabilityFor[workspace]));

  useEffect(() => {
    if (!sdkReady || !me) return;
    if (!me.authenticated) {
      router.replace("/login");
      return;
    }
    if (!allowed) router.replace("/workspace");
  }, [allowed, me, router, sdkReady]);

  if (!sdkReady || !me) {
    return (
      <div className="flex min-h-svh items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }
  if (!me.authenticated || !allowed) return null;

  return (
    <SidebarProvider>
      <AppSidebar workspace={workspace} />
      {/* veyra-scope maps the shadcn tokens onto the Veyra palette for the
          whole authenticated surface, so client and agent pages inherit the
          same background, borders and text colours without per-page overrides. */}
      {/* The inset is the flex column, not a nested div. Previously a
          `min-h-screen` wrapper sat *after* the sticky header, so the column
          measured a full viewport on top of the header height and the footer
          was pushed permanently below the fold. The inset already fills the
          viewport, so main simply grows and the footer follows it. */}
      <SidebarInset className="veyra-scope dashboard-shell flex min-h-svh flex-col">
        <Header workspace={workspace} />
        <main className="mx-auto w-full max-w-[1280px] flex-1 space-y-6 px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  );
}
