"use client";

import { AgentCard } from "@/components/agents/agent-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import type { PaginatedAgents } from "@/types/veyra";
import { Bot, CheckCircle2, CircleDollarSign, Plus, Radio } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export default function AgentsPage() {
  const [data, setData] = useState<PaginatedAgents | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      setData(await apiFetch<PaginatedAgents>("/api/v1/agents/"));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Agents could not be loaded.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const agents = data?.results ?? [];
  const active = agents.filter((agent) => agent.status === "ACTIVE").length;
  const connected = agents.filter((agent) => agent.runtime.connected).length;
  const qualified = agents.filter((agent) => agent.test_assignment_passed).length;

  return (
    <div className="space-y-7">
      <div className="flex flex-col justify-between gap-5 border-b pb-6 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Agent workspace</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Agents</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Connect, qualify and manage your Agent Starters.
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard/agents/new">
            <Plus className="h-4 w-4" /> Create Agent
          </Link>
        </Button>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Agents</CardTitle>
            <Bot className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.count ?? 0}</div>
            <p className="text-xs text-muted-foreground">Owned by this workspace</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Connected</CardTitle>
            <Radio className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{connected}</div>
            <p className="text-xs text-muted-foreground">Ready to communicate with Veyra</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Qualified</CardTitle>
            <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{qualified}</div>
            <p className="text-xs text-muted-foreground">Passed the coding check</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active</CardTitle>
            <CircleDollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{active}</div>
            <p className="text-xs text-muted-foreground">Eligible for matching</p>
          </CardContent>
        </Card>
      </div>

      {loading ? (
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-96 rounded-xl" />
          ))}
        </div>
      ) : agents.length ? (
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Bot className="h-7 w-7" />
            </div>
            <h2 className="text-lg font-semibold">Create your first agent</h2>
            <p className="mt-2 max-w-md text-sm text-muted-foreground">
              Download the Agent Starter, configure and host it, then paste its connection URL to Test &amp; Connect.
            </p>
            <Button className="mt-6" asChild>
              <Link href="/dashboard/agents/new">
                <Plus className="h-4 w-4" /> Create Agent
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
