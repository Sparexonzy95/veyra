import { cn } from "@/lib/utils";

/**
 * One list definition, two presentations.
 *
 * Desktop renders a real semantic table. Mobile renders the same rows as
 * stacked cards, driven by the same column config. Declaring the data once
 * is what keeps client and agent lists identical, and it removes the
 * horizontal scrolling that a min-width table forces on small screens.
 *
 * Columns marked `primary` lead the stacked mobile item. Columns marked
 * `hideOnMobile` are dropped there, because a phone row should carry the
 * important facts, not every column.
 */
export type Column<T> = {
  key: string;
  header: string;
  /** Leads the mobile stacked item and is emphasised on desktop. */
  primary?: boolean;
  /** Dropped from the mobile presentation. */
  hideOnMobile?: boolean;
  /** Right-aligned on desktop, typically the row action. */
  align?: "left" | "right";
  className?: string;
  render: (row: T) => React.ReactNode;
};

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  className,
}: {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  className?: string;
}) {
  const primary = columns.find((column) => column.primary) ?? columns[0];
  const mobileColumns = columns.filter(
    (column) => column !== primary && !column.hideOnMobile,
  );

  return (
    <div className={className}>
      {/* Desktop: semantic table, compact rows, muted separators. */}
      <table className="hidden w-full text-left text-sm md:table">
        <thead>
          <tr className="border-b border-border">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground",
                  column.align === "right" && "text-right",
                  column.className,
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className="border-b border-border/60 last:border-0 hover:bg-muted/30"
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    "px-4 py-3 align-middle",
                    column.primary
                      ? "max-w-[320px] font-medium"
                      : "text-muted-foreground",
                    column.align === "right" && "text-right",
                    column.className,
                  )}
                >
                  {column.primary ? (
                    <span className="block truncate">{column.render(row)}</span>
                  ) : (
                    column.render(row)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Mobile: the same rows as compact stacked items. */}
      <ul className="divide-y divide-border md:hidden">
        {rows.map((row) => (
          <li key={rowKey(row)} className="px-4 py-3.5">
            <div className="text-sm font-medium">{primary.render(row)}</div>
            {mobileColumns.length ? (
              <dl className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                {mobileColumns.map((column) => (
                  <div
                    key={column.key}
                    className="flex items-center gap-1.5 text-xs"
                  >
                    <dt className="text-muted-foreground">{column.header}</dt>
                    <dd className="font-medium">{column.render(row)}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
