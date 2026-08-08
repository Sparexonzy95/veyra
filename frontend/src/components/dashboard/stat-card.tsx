import { cn } from "@/lib/utils";
import { LucideIcon } from "lucide-react";

/**
 * Compact statistic card. These live inside grids, so their height
 * must be consistent and their padding must be restrained.
 */
export function StatCard({
  label,
  value,
  icon: Icon,
  trend,
  className,
}: {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  trend?: { value: string; direction: "up" | "down" | "neutral" };
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card p-4 shadow-sm",
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        {Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null}
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight">{value}</p>
      {trend ? (
        <p
          className={cn("mt-1 text-xs font-medium", {
            "text-green-600 dark:text-green-400": trend.direction === "up",
            "text-red-600 dark:text-red-400": trend.direction === "down",
            "text-muted-foreground": trend.direction === "neutral",
          })}
        >
          {trend.value}
        </p>
      ) : null}
    </div>
  );
}
