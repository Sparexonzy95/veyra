"use client";

import { AgentStatusBadge } from "@/components/agents/agent-status-badge";
import { HostedRuntimeCard } from "@/components/agents/hosted-runtime-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { AgentSummary } from "@/types/veyra";
import {
  ArrowLeft,
  Bot,
  Check,
  CircleDollarSign,
  Clock3,
  Radio,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

const onboardingSteps: Array<{
  key: keyof AgentSummary["onboarding"]["checks"];
  label: string;
  description: string;
}> = [
  { key: "identity", label: "Agent identity", description: "Profile and focused capability are saved." },
  { key: "runtime", label: "Hosted runtime", description: "Veyra automatically provides the secure execution environment." },
  { key: "wallet", label: "Arc wallet", description: "A dedicated Circle developer-controlled wallet exists." },
  { key: "worker_authorisation", label: "Contract authorisation", description: "The worker wallet is authorised on VeyraJobEscrow." },
  { key: "capabilities", label: "Work policy", description: "Capabilities, limits, and protected paths are configured." },
  { key: "qualification", label: "Qualification", description: "The controlled test assignment has passed." },
];

function formatStep(value: AgentSummary["onboarding"]["current_step"]) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shortAddress(value: string) {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "Not created";
}

export default function AgentDetailPage() {
  const params = useParams<{ id: string }>();
  const [agent, setAgent] = useState<AgentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const loaded = await apiFetch<AgentSummary>(`/api/v1/agents/${params.id}/`);
        setAgent(loaded);
        setError(null);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Agent could not be loaded.");
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [params.id],
  );

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const capabilities = useMemo(() => {
    if (!agent) return [];
    return [
      ...agent.languages,
      ...agent.frameworks,
      ...agent.testing_tools,
      ...agent.task_types,
    ];
  }, [agent]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-36" />
        <Skeleton className="h-28 rounded-xl" />
        <div className="grid gap-6 lg:grid-cols-[1.3fr_0.7fr]">
          <Skeleton className="h-[34rem] rounded-xl" />
          <Skeleton className="h-[34rem] rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" asChild className="px-0">
          <Link href="/dashboard/agents">
            <ArrowLeft className="h-4 w-4" /> Back to Agents
          </Link>
        </Button>
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error ?? "Agent not found."}
        </div>
      </div>
    );
  }

  const completedSteps = onboardingSteps.filter((step) => agent.onboarding.checks[step.key]).length;
  const progress = Math.round((completedSteps / onboardingSteps.length) * 100);

  return (
    <div className="space-y-6">
      <Button variant="ghost" asChild className="px-0">
        <Link href="/dashboard/agents">
          <ArrowLeft className="h-4 w-4" /> Back to Agents
        </Link>
      </Button>

      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Bot className="h-7 w-7" />
          </div>
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <AgentStatusBadge status={agent.status} />
              <Badge variant="outline">
                {agent.specialisation.replaceAll("_", " ").toLowerCase()}
              </Badge>
            </div>
            <h1 className="text-2xl font-bold tracking-tight md:text-3xl">{agent.name}</h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              {agent.description || "No description added yet."}
            </p>
          </div>
        </div>
      </div>

      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
            <CardTitle>Onboarding Progress</CardTitle>
            <span className="text-sm font-medium">
              {completedSteps} of {onboardingSteps.length} complete
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} />
          </div>
          <p className="text-sm text-muted-foreground">
            Current step: <strong className="text-foreground">{formatStep(agent.onboarding.current_step)}</strong>
          </p>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {onboardingSteps.map((step) => {
            const complete = agent.onboarding.checks[step.key];
            return (
              <div key={step.key} className="flex items-start gap-3 rounded-xl border p-4">
                <div
                  className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                    complete ? "bg-emerald-500/10 text-emerald-600" : "bg-muted text-muted-foreground"
                  }`}
                >
                  {complete ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
                </div>
                <div>
                  <p className="text-sm font-medium">{step.label}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{step.description}</p>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <HostedRuntimeCard agent={agent} onRefresh={() => load(true)} />

        <Card>
          <CardHeader>
            <CardTitle>Agent Connections</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-muted-foreground">
                <Radio className="h-4 w-4" /> Runtime
              </span>
              <span className="font-medium">
                {agent.runtime.runtime_mode === "VEYRA_HOSTED"
                  ? agent.runtime.connected
                    ? "Veyra-hosted · ready"
                    : "Veyra-hosted · preparing"
                  : agent.runtime.status.replaceAll("_", " ").toLowerCase()}
              </span>
            </div>
            <Separator />
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Repository access</span>
              <span className="text-right font-medium">Provided by each client job</span>
            </div>
            <Separator />
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-muted-foreground">
                <Wallet className="h-4 w-4" /> Arc wallet
              </span>
              <span className="font-mono text-xs">{shortAddress(agent.worker_wallet_address)}</span>
            </div>
            <Separator />
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-muted-foreground">
                <ShieldCheck className="h-4 w-4" /> Contract
              </span>
              <span className="font-medium">
                {agent.contract_authorised ? "Authorised" : "Not authorised"}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Capabilities</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {capabilities.map((capability) => (
              <Badge key={capability} variant="outline">
                {capability}
              </Badge>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Work Policy</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Budget range</p>
              <p className="mt-1 flex items-center gap-1 font-medium">
                <CircleDollarSign className="h-4 w-4" />
                {agent.minimum_budget_usdc} to {agent.maximum_budget_usdc} USDC
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Execution limit</p>
              <p className="mt-1 flex items-center gap-1 font-medium">
                <Clock3 className="h-4 w-4" /> {agent.maximum_execution_minutes} minutes
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Concurrent jobs</p>
              <p className="mt-1 font-medium">{agent.maximum_active_jobs}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Repository access</p>
              <p className="mt-1 font-medium">
                {agent.public_repositories_only ? "Public repositories only" : "Configured repositories"}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
