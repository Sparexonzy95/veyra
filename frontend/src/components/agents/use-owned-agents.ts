"use client";

import { apiFetch } from "@/lib/api";
import type { AgentSummary, PaginatedAgents } from "@/types/veyra";
import { useCallback, useEffect, useState } from "react";

export function useOwnedAgents() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await apiFetch<PaginatedAgents>("/api/v1/agents/");
      setAgents(page.results);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Agent data could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  return { agents, loading, error, reload: load };
}
