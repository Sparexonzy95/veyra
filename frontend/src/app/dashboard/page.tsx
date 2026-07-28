"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function LegacyDashboardRedirect() {
  const { me, sdkReady } = useVeyra();
  const router = useRouter();
  useEffect(() => {
    if (!sdkReady || !me) return;
    if (!me.authenticated) {
      router.replace("/login");
    } else if (me.capabilities?.includes("CLIENT")) {
      router.replace("/client");
    } else if (me.capabilities?.includes("AGENT_OWNER")) {
      router.replace("/agent-owner");
    } else {
      router.replace("/workspace");
    }
  }, [me, router, sdkReady]);
  return <div className="flex min-h-svh items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
}
