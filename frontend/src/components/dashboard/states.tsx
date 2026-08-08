import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AlertCircle, LucideIcon } from "lucide-react";

/**
 * Empty, loading and error states for every dashboard list and table.
 *
 * These exist so a page never invents its own version of "nothing here yet",
 * which is the most common source of visual drift between sections.
 */

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-12 text-center",
        className,
      )}
    >
      {Icon ? (
        <div className="rounded-full border border-border bg-muted/40 p-3">
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
      ) : null}
      <div>
        <p className="text-sm font-medium">{title}</p>
        {description ? (
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
        <p className="text-sm text-destructive">{message}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="shrink-0">
          Try again
        </Button>
      ) : null}
    </div>
  );
}

/**
 * Skeleton rows sized to match the real table/list rows they replace, so
 * the page does not jump when data arrives.
 */
export function LoadingRows({
  rows = 4,
  className,
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <div className={cn("divide-y divide-border", className)}>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-center gap-4 px-4 py-3.5">
          <div className="h-4 flex-1 animate-pulse rounded bg-muted" />
          <div className="hidden h-4 w-24 animate-pulse rounded bg-muted sm:block" />
          <div className="h-5 w-20 animate-pulse rounded-full bg-muted" />
        </div>
      ))}
    </div>
  );
}

export function LoadingCards({
  count = 4,
  className,
}: {
  count?: number;
  className?: string;
}) {
  return (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className={cn(
            "rounded-lg border border-border bg-card p-4 shadow-sm",
            className,
          )}
        >
          <div className="h-3 w-20 animate-pulse rounded bg-muted" />
          <div className="mt-3 h-7 w-14 animate-pulse rounded bg-muted" />
        </div>
      ))}
    </>
  );
}
