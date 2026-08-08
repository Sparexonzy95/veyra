"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { Panel } from "@/components/dashboard/panel";
import {
  DashboardPagination,
  PAGE_SIZE,
  pageCount,
  usePageParam,
} from "@/components/dashboard/pagination";
import { EmptyState, ErrorState, LoadingRows } from "@/components/dashboard/states";
import { apiFetch } from "@/lib/api";
import type { DashboardResponse } from "@/types/veyra";
import { Activity } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export default function ClientActivityPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiFetch<DashboardResponse>("/api/v1/client/dashboard/"));
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Activity could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const notifications = useMemo(
    () => data?.notifications ?? [],
    [data?.notifications],
  );
  const { page, setPage } = usePageParam();
  const totalPages = pageCount(notifications.length, PAGE_SIZE.activity);
  // `/api/v1/client/dashboard/` is a plain APIView that returns the whole
  // notification set in one payload, so the slice happens here. If that
  // endpoint gains `?page=`, only this block changes.
  const visible = notifications.slice(
    (page - 1) * PAGE_SIZE.activity,
    page * PAGE_SIZE.activity,
  );
  const headingRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <PageHeader title="Activity" description="Review recent platform events." />

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <Panel className="overflow-hidden" ref={headingRef}>
        {loading ? (
          <LoadingRows rows={PAGE_SIZE.activity} />
        ) : visible.length ? (
          <ul className="divide-y divide-border">
            {visible.map((item) => (
              <li key={item.id} className="flex gap-3 px-4 py-3.5">
                <Activity
                  className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                  aria-hidden
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{item.title}</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {item.body}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {new Date(item.created_at).toLocaleString()}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={Activity}
            title="No activity yet"
            description="Events appear here as your jobs progress."
          />
        )}
        {!loading && notifications.length ? (
          <DashboardPagination
            page={page}
            totalPages={totalPages}
            totalItems={notifications.length}
            onPageChange={setPage}
            scrollTargetRef={headingRef}
          />
        ) : null}
      </Panel>
    </>
  );
}
