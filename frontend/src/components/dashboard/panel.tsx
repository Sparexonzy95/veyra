import { cn } from "@/lib/utils";
import { forwardRef } from "react";

/**
 * The one card/surface used across both dashboards.
 *
 * Cards never set a fixed height: equal heights come from the grid
 * (`items-stretch` plus `h-full`), so content decides the size and rows
 * still line up.
 *
 * Ref-forwarding exists so a paginated list can use its own Panel as the
 * scroll target after a page change, instead of each page adding a wrapper
 * element purely to hang a ref on.
 */
export const Panel = forwardRef<
  HTMLDivElement,
  { className?: string; children: React.ReactNode }
>(function Panel({ className, children }, ref) {
  return (
    <div
      ref={ref}
      className={cn(
        "rounded-lg border border-border bg-card shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
});

/**
 * Panel header with an optional trailing action. Uses the same 16px
 * horizontal padding as PanelBody so content stays on one vertical rhythm.
 */
export function PanelHeader({
  title,
  action,
  className,
}: {
  title: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-b border-border px-4 py-3",
        className,
      )}
    >
      <h2 className="text-sm font-semibold">{title}</h2>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function PanelBody({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cn("p-4", className)}>{children}</div>;
}
