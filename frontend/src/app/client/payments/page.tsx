"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { Panel, PanelHeader } from "@/components/dashboard/panel";
import {
  DashboardPagination,
  PAGE_SIZE,
  pageCount,
  usePageParam,
} from "@/components/dashboard/pagination";
import { EmptyState, ErrorState, LoadingRows } from "@/components/dashboard/states";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { apiFetch } from "@/lib/api";
import type { CircleTransactionStatus } from "@/types/veyra";
import { ReceiptText } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

function purposeLabel(purpose: string) {
  return purpose
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function ClientPaymentsPage() {
  const [transactions, setTransactions] = useState<CircleTransactionStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Balance and network now live in the top-bar wallet popover, so this page
  // no longer fetches the wallet to restate them. It loads payment activity
  // only, which is what distinguishes it from the popover.
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await apiFetch<{ results: CircleTransactionStatus[] }>(
        "/api/v1/client/transactions/",
      );
      setTransactions(page.results);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Payments could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const { page, setPage } = usePageParam();
  const totalPages = pageCount(transactions.length, PAGE_SIZE.payments);
  // CircleTransactionListView is a plain APIView with no `?page=`, so the
  // slice is local. The payload is one client's transactions, not an
  // unbounded table.
  const visible = transactions.slice(
    (page - 1) * PAGE_SIZE.payments,
    page * PAGE_SIZE.payments,
  );
  const listRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <PageHeader
        title="Payments"
        description="Funding and settlement history for your jobs."
      />

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <Panel className="overflow-hidden" ref={listRef}>
        <PanelHeader title="Payment activity" />
        {loading ? (
          <LoadingRows rows={PAGE_SIZE.payments} />
        ) : visible.length ? (
          <ul className="divide-y divide-border">
            {visible.map((transaction) => (
              <li
                key={transaction.id}
                className="flex items-center justify-between gap-4 px-4 py-3.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {purposeLabel(transaction.purpose)}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {new Date(transaction.created_at).toLocaleString()}
                  </p>
                </div>
                <StatusBadge status={transaction.status} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={ReceiptText}
            title="No payment activity yet"
            description="Funding and settlement events appear here."
          />
        )}
        {!loading && transactions.length ? (
          <DashboardPagination
            page={page}
            totalPages={totalPages}
            totalItems={transactions.length}
            onPageChange={setPage}
            scrollTargetRef={listRef}
          />
        ) : null}
      </Panel>
    </>
  );
}
