import { cn } from "@/lib/utils";

/**
 * The single page-header pattern for every client and agent dashboard page.
 *
 * Left: short title plus at most one supporting line.
 * Right: one primary action, optionally one secondary action.
 *
 * Long introductions belong in documentation, not on a working page, so
 * `description` is deliberately a single line.
 */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-col justify-between gap-3 border-b border-border pb-4 sm:flex-row sm:items-end",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="truncate text-xl font-semibold tracking-[-0.02em] sm:text-2xl">
          {title}
        </h1>
        {description ? (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </header>
  );
}

/**
 * Section heading used inside a page, one step below PageHeader.
 */
export function SectionHeader({
  title,
  action,
  className,
}: {
  title: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <h2 className="text-sm font-semibold">{title}</h2>
      {action}
    </div>
  );
}
