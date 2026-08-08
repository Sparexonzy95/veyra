"use client";

import { apiFetch } from "@/lib/api";
import type { AgentSummary, PaginatedAgents } from "@/types/veyra";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The owner's agents, shared across the pages that read them.
 *
 * Assignments, Earnings and Reputation all derive their content from this one
 * payload. Previously each of them mounted its own copy of this hook, so
 * moving between those three tabs fired `/api/v1/agents/` three times and each
 * page began empty — the request, not the render, was what made tab switching
 * feel slow.
 *
 * So the result is cached at module scope and handed to the next page
 * synchronously on mount. A revalidation still runs in the background, but the
 * user sees content immediately instead of a skeleton they have already
 * waited through once. Concurrent mounts share a single in-flight promise
 * rather than racing duplicate requests.
 *
 * The cache is deliberately per-tab and in-memory: it dies with the page, so
 * it can never serve one account's agents to another after a logout and
 * re-login.
 */

const STALE_AFTER_MS = 15_000;

type Cache = {
  agents: AgentSummary[];
  fetchedAt: number;
};

let cache: Cache | null = null;
let inFlight: Promise<AgentSummary[]> | null = null;

/** Drops the cache. Called on logout so a new session starts clean. */
export function clearOwnedAgentsCache() {
  cache = null;
  inFlight = null;
}

function fetchOwnedAgents() {
  // A second caller during an active request waits on the same promise
  // instead of issuing its own.
  if (!inFlight) {
    inFlight = apiFetch<PaginatedAgents>("/api/v1/agents/")
      .then((page) => {
        cache = { agents: page.results, fetchedAt: Date.now() };
        return page.results;
      })
      .finally(() => {
        inFlight = null;
      });
  }
  return inFlight;
}

export function useOwnedAgents() {
  const [agents, setAgents] = useState<AgentSummary[]>(cache?.agents ?? []);
  // Only a genuinely cold start is "loading". With a warm cache the page has
  // content to draw, so showing a skeleton over it would be a lie.
  const [loading, setLoading] = useState(!cache);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(async (force = false) => {
    const fresh =
      cache && !force && Date.now() - cache.fetchedAt < STALE_AFTER_MS;
    if (fresh) {
      setAgents(cache!.agents);
      setLoading(false);
      return;
    }

    if (!cache) setLoading(true);
    try {
      const next = await fetchOwnedAgents();
      // The user may have navigated away mid-request; setting state on an
      // unmounted page is how "stuck" spinners and stray errors appear.
      if (!mounted.current) return;
      setAgents(next);
      setError(null);
    } catch (loadError) {
      if (!mounted.current) return;
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Agent data could not be loaded.",
      );
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = useCallback(() => load(true), [load]);

  return { agents, loading, error, reload };
}
