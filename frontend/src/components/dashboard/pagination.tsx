"use client";

import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useRef } from "react";

/**
 * The single pagination control for every dashboard list.
 *
 * Page sizes are declared here rather than per page, so a list cannot quietly
 * drift to its own size. Explore Issues stays at 6 because the backend's
 * PublicIssuePagination is fixed at 6; the card size matches it deliberately.
 */
export const PAGE_SIZE = {
  /** Single-line tables and row lists. */
  table: 10,
  /** Card grids, including Explore Issues. */
  cards: 6,
  /**
   * Activity rows carry a title, a body and a timestamp, so each one is
   * roughly three times the height of a table row. Six of them already fill
   * more screen than ten payment rows do; ten would push the pagination
   * control well below the fold.
   */
  activity: 6,
  /**
   * Payment rows are two lines (purpose plus timestamp) with a status badge,
   * and the list sits under a panel header on a page that has no other
   * content. Six keeps the whole panel, pagination included, on one screen.
   */
  payments: 6,
} as const;

/** Total pages for a record count, never less than one. */
export function pageCount(total: number, size: number) {
  return Math.max(1, Math.ceil(total / size));
}

/**
 * Page state in the URL, so a paged list survives refresh, back/forward and
 * sharing. Filters and search are untouched here — this only ever reads and
 * writes `page`, and it deletes the parameter on page 1 to keep clean URLs.
 *
 * `resetToFirstPage` is what callers use when a filter changes: paging to
 * "page 4 of a different filter" is the classic way to land on an empty list.
 */
export function usePageParam(key = "page") {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const page = Math.max(1, Number(searchParams.get(key)) || 1);

  const write = useCallback(
    (next: number) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next > 1) params.set(key, String(next));
      else params.delete(key);
      const query = params.toString();
      // `scroll: false` because DashboardPagination restores position itself,
      // to the list heading rather than to the top of the document.
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [key, pathname, router, searchParams],
  );

  const resetToFirstPage = useCallback(() => {
    if (page !== 1) write(1);
  }, [page, write]);

  return { page, setPage: write, resetToFirstPage };
}

/**
 * Window of page numbers around the current page, with first and last always
 * present and ellipses where the sequence breaks.
 */
function pageWindow(current: number, total: number) {
  const wanted = new Set([1, total, current, current - 1, current + 1]);
  return [...wanted]
    .filter((page) => page >= 1 && page <= total)
    .sort((a, b) => a - b);
}

export function DashboardPagination({
  page,
  totalPages,
  totalItems,
  onPageChange,
  /**
   * Scrolled back into view after a page change so the user lands on the list
   * heading instead of wherever the previous page's rows left them.
   */
  scrollTargetRef,
  className,
}: {
  page: number;
  totalPages: number;
  totalItems?: number;
  onPageChange: (page: number) => void;
  /** Any element ref; pages typically pass the list Panel's own div ref. */
  scrollTargetRef?: React.RefObject<HTMLElement | null> | React.RefObject<HTMLDivElement | null>;
  className?: string;
}) {
  const fallbackRef = useRef<HTMLElement | null>(null);
  const target = scrollTargetRef ?? fallbackRef;
  const pages = useMemo(
    () => pageWindow(page, totalPages),
    [page, totalPages],
  );

  const change = useCallback(
    (next: number) => {
      if (next < 1 || next > totalPages || next === page) return;
      onPageChange(next);
      // After the row swap, not before, or the browser scrolls to the old
      // layout and the heading ends up off screen.
      requestAnimationFrame(() =>
        target.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
    },
    [onPageChange, page, target, totalPages],
  );

  // A single page needs no control, but the count is still useful.
  if (totalPages <= 1) return null;

  return (
    <nav
      aria-label="Pagination"
      className={cn(
        "flex flex-col items-center gap-3 border-t border-border px-4 py-3 sm:flex-row sm:justify-between",
        className,
      )}
    >
      <p className="order-2 text-xs text-muted-foreground sm:order-1">
        Page {page} of {totalPages}
        {typeof totalItems === "number" ? ` · ${totalItems} total` : ""}
      </p>
      <div className="order-1 flex items-center gap-1 sm:order-2">
        <PageButton
          onClick={() => change(page - 1)}
          disabled={page <= 1}
          label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">Previous</span>
        </PageButton>

        {pages.map((entry, index) => (
          <span key={entry} className="flex items-center gap-1">
            {pages[index - 1] !== undefined && entry - pages[index - 1] > 1 ? (
              <span
                aria-hidden
                className="px-0.5 text-xs text-muted-foreground"
              >
                …
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => change(entry)}
              aria-label={`Page ${entry}`}
              aria-current={entry === page ? "page" : undefined}
              className={cn(
                "inline-flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                entry === page
                  ? "bg-primary text-primary-foreground"
                  : "border border-border text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              {entry}
            </button>
          </span>
        ))}

        <PageButton
          onClick={() => change(page + 1)}
          disabled={page >= totalPages}
          label="Next page"
        >
          <span className="hidden sm:inline">Next</span>
          <ChevronRight className="h-4 w-4" aria-hidden />
        </PageButton>
      </div>
    </nav>
  );
}

function PageButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="inline-flex h-8 items-center gap-1 rounded-md border border-border px-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:px-2.5"
    >
      {children}
    </button>
  );
}
