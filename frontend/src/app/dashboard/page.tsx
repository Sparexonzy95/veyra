"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { resolveAuthDestination } from "@/lib/auth-destination";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Legacy `/dashboard` entry point.
 *
 * This used to branch on capabilities and drop a CLIENT user directly on
 * `/client`, which meant the destination after sign-in depended on which
 * surface ran its effect first. It now defers to `resolveAuthDestination`
 * like every other authenticated entry point, so every user lands on the
 * shared chooser and can reach either side of Veyra.
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
