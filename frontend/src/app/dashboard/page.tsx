"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { resolveAuthDestination } from "@/lib/auth-destination";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Compatibility entry point for older dashboard URLs.
 * Authenticated users are routed through the canonical Veyra destination resolver.
 */
export default function LegacyDashboardRedirect() {
  const { me, sdkReady } = useVeyra();
  const router = useRouter();

  useEffect(() => {
    if (!sdkReady || !me) return;
    if (!me.authenticated) {
      router.replace("/login");
      return;
    }
    router.replace(resolveAuthDestination(me.capabilities));
  }, [me, router, sdkReady]);

  return (
    <div className="flex min-h-svh items-center justify-center bg-veyra-ink">
      <Loader2 className="h-6 w-6 animate-spin text-veyra-sand motion-reduce:animate-none" />
    </div>
  );
}
