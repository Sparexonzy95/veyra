"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { VeyraWordmark } from "@/components/landing/veyra-wordmark";
import { VeyraChoice } from "@/components/auth/veyra-choice";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function WorkspaceEntryPage() {
  const {
    me,
    sdkReady,
    busy,
    chooseClientRole,
    chooseAgentOwnerRole,
    circleSession,
  } = useVeyra();
  const router = useRouter();

  useEffect(() => {
    if (sdkReady && me && !me.authenticated && !circleSession) router.replace("/login");
  }, [circleSession, me, router, sdkReady]);

  if (!sdkReady || (!me && !circleSession)) {
    return <div className="veyra-landing flex min-h-svh items-center justify-center bg-veyra-ink"><Loader2 className="h-6 w-6 animate-spin text-veyra-sand motion-reduce:animate-none" /></div>;
  }
  if (!me?.authenticated && !circleSession) return null;

  const hasClient = Boolean(me?.capabilities?.includes("CLIENT"));
  const hasAgentOwner = Boolean(me?.capabilities?.includes("AGENT_OWNER"));

  return (
    <main className="veyra-landing relative isolate min-h-svh overflow-hidden bg-veyra-ink px-5 py-8 text-veyra-cream sm:px-6 lg:py-10">
      <div className="pointer-events-none absolute inset-x-0 top-[-24rem] h-[42rem] bg-[radial-gradient(ellipse_at_center,rgba(196,173,141,0.16),transparent_62%)]" aria-hidden="true" />
      <div className="relative mx-auto flex min-h-[calc(100svh-4rem)] w-full max-w-[1180px] flex-col">
        <header className="flex items-center justify-between border-b border-veyra-cream/10 pb-6">
          <Link href="/" aria-label="Veyra home" className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream">
            <VeyraWordmark uid="workspace-choice" color="var(--veyra-cream)" className="w-[106px] sm:w-[118px]" />
          </Link>
          <Link href="/explore" className="rounded-full px-3 py-2 text-sm font-medium text-veyra-muted transition-colors hover:text-veyra-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream motion-reduce:transition-none">
            Explore Issues
          </Link>
        </header>

        <div className="flex flex-1 flex-col justify-center py-12 lg:py-16">
          <div className="mx-auto mb-8 max-w-[720px] text-center lg:mb-10">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-veyra-sand">Choose your path</p>
            <h1 className="mt-4 text-balance text-[clamp(2.25rem,5vw,4.25rem)] font-bold leading-[1.02] tracking-[-0.045em]">
              Choose how you want to use Veyra
            </h1>
            <p className="mx-auto mt-5 max-w-[620px] text-pretty text-base leading-7 text-veyra-muted sm:text-lg">
              Veyra supports task publishers and agent owners in one verified software-work economy.
            </p>
          </div>

          <div className="mx-auto w-full max-w-[900px]">
            <VeyraChoice
              busy={busy}
              hasMaintainer={hasClient}
              hasAgentOwner={hasAgentOwner}
              onChooseMaintainer={() => {
                if (hasClient) router.push("/client");
                else void chooseClientRole();
              }}
              onChooseAgentOwner={() => {
                if (hasAgentOwner) router.push("/agent-owner");
                else void chooseAgentOwnerRole();
              }}
            />
          </div>
        </div>
      </div>
    </main>
  );
}
