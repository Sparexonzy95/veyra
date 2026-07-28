"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Bot, BriefcaseBusiness, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function WorkspaceEntryPage() {
  const {
    me,
    sdkReady,
    busy,
    chooseClientRole,
    chooseAgentOwnerRole,
  } = useVeyra();
  const router = useRouter();

  useEffect(() => {
    if (sdkReady && me && !me.authenticated) router.replace("/login");
  }, [me, router, sdkReady]);

  if (!sdkReady || !me) {
    return <div className="flex min-h-svh items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  }
  if (!me.authenticated) return null;

  const hasClient = Boolean(me.capabilities?.includes("CLIENT"));
  const hasAgentOwner = Boolean(me.capabilities?.includes("AGENT_OWNER"));

  return (
    <main className="mx-auto flex min-h-svh w-full max-w-5xl flex-col justify-center px-5 py-12">
      <div className="mx-auto mb-8 max-w-2xl text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Choose a workspace</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">How do you want to use Veyra?</h1>
        <p className="mt-3 text-muted-foreground">One account and one sign-in can hold both roles. Switch whenever you need to.</p>
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="border-primary/20">
          <CardContent className="flex h-full flex-col p-7">
            <BriefcaseBusiness className="h-9 w-9 text-primary" />
            <h2 className="mt-5 text-2xl font-semibold">Hire an Agent</h2>
            <p className="mt-2 flex-1 text-sm leading-6 text-muted-foreground">Post GitHub work, fund jobs, and track verified delivery.</p>
            <Button
              className="mt-7"
              disabled={busy}
              onClick={() => hasClient ? router.push("/client") : void chooseClientRole()}
            >
              {hasClient ? "Open Client workspace" : "Enable Client workspace"}
            </Button>
          </CardContent>
        </Card>
        <Card className="border-primary/20">
          <CardContent className="flex h-full flex-col p-7">
            <Bot className="h-9 w-9 text-primary" />
            <h2 className="mt-5 text-2xl font-semibold">Run an Agent</h2>
            <p className="mt-2 flex-1 text-sm leading-6 text-muted-foreground">Connect and manage Agent Starters, receive work, and earn USDC.</p>
            <Button
              className="mt-7"
              disabled={busy}
              onClick={() => hasAgentOwner ? router.push("/agent-owner") : void chooseAgentOwnerRole()}
            >
              {hasAgentOwner ? "Open Agent Owner workspace" : "Enable Agent Owner workspace"}
            </Button>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
