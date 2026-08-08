import type { IssueSort, PublicIssueFacets } from "@/lib/explore-issues";
import { Search, SlidersHorizontal } from "lucide-react";

export const SORT_OPTIONS: { value: IssueSort; label: string }[] = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "reward", label: "Reward: High to Low" },
  { value: "deadline", label: "Deadline: Soonest" },
];

export type ExploreFilters = {
  project: string;
  taskType: string;
  label: string;
  techStack: string;
  minReward: string;
  maxReward: string;
  verification: string;
  sort: IssueSort;
};

type IssueFiltersProps = {
  facets: PublicIssueFacets | null;
  facetsFailed: boolean;
  search: string;
  values: ExploreFilters;
  activeCount: number;
  onSearchChange: (value: string) => void;
  onChange: (key: keyof ExploreFilters, value: string) => void;
  onClear: () => void;
};

const selectClass =
  "mt-2 h-10 w-full rounded-xl border border-veyra-cream/10 bg-veyra-ink px-3 text-sm text-veyra-cream outline-none transition-colors focus-visible:border-veyra-sand/50 focus-visible:ring-2 focus-visible:ring-veyra-sand/20 disabled:cursor-not-allowed disabled:opacity-50";

export function MobileIssueFilters(props: IssueFiltersProps) {
  return (
    <details className="group mb-6 rounded-[18px] border border-veyra-cream/10 bg-veyra-ink-raised/75 lg:hidden">
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-4 px-4 text-sm font-semibold text-veyra-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-veyra-sand/40 [&::-webkit-details-marker]:hidden">
        <span className="inline-flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4 text-veyra-sand" aria-hidden="true" />
          Filters
          {props.activeCount ? (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-veyra-sand px-1.5 text-[0.65rem] font-bold text-veyra-ink">
              {props.activeCount}
            </span>
          ) : null}
        </span>
        <span className="text-xs font-medium text-veyra-muted-dark group-open:hidden">Show</span>
        <span className="hidden text-xs font-medium text-veyra-muted-dark group-open:inline">Hide</span>
      </summary>
      <div className="border-t border-veyra-cream/10 p-4">
        <IssueFilterControls {...props} />
      </div>
    </details>
  );
}

export function DesktopIssueFilters(props: IssueFiltersProps) {
  return (
    <aside className="sticky top-28 hidden self-start rounded-[22px] border border-veyra-cream/[0.12] bg-veyra-ink-raised/80 p-5 shadow-[0_20px_70px_rgba(0,0,0,0.2)] lg:block">
      <IssueFilterControls {...props} />
    </aside>
  );
}

function IssueFilterControls({
  facets,
  facetsFailed,
  search,
  values,
  activeCount,
  onSearchChange,
  onChange,
  onClear,
}: IssueFiltersProps) {
  const disabled = !facets;
  return (
    <div>
      <div className="flex items-start justify-between gap-3 border-b border-veyra-cream/10 pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-veyra-muted-dark">Total open issues</p>
          <p className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-veyra-cream">
            {facets ? facets.total_open : "—"}
          </p>
        </div>
        {activeCount ? (
          <button
            type="button"
            onClick={onClear}
            className="rounded-full px-2 py-1 text-xs font-semibold text-veyra-sand outline-none transition-colors hover:bg-veyra-sand/10 focus-visible:ring-2 focus-visible:ring-veyra-sand/40"
          >
            Clear all
          </button>
        ) : null}
      </div>

      <FilterSection label="Search">
        <div className="relative mt-2">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-veyra-muted-dark"
            aria-hidden="true"
          />
          <input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Title, repository, keyword"
            aria-label="Search open issues"
            className="h-10 w-full rounded-xl border border-veyra-cream/10 bg-veyra-ink pl-9 pr-3 text-sm text-veyra-cream outline-none placeholder:text-veyra-muted-dark focus-visible:border-veyra-sand/50 focus-visible:ring-2 focus-visible:ring-veyra-sand/20"
          />
        </div>
      </FilterSection>

      <FilterSelect
        label="Project"
        value={values.project}
        options={facets?.projects ?? []}
        disabled={disabled}
        onChange={(value) => onChange("project", value)}
      />
      <FilterSelect
        label="Task type"
        value={values.taskType}
        options={facets?.task_types ?? []}
        disabled={disabled}
        onChange={(value) => onChange("taskType", value)}
      />
      <FilterSelect
        label="Label"
        value={values.label}
        options={facets?.labels ?? []}
        disabled={disabled}
        onChange={(value) => onChange("label", value)}
      />
      <FilterSelect
        label="Tech stack"
        value={values.techStack}
        options={facets?.tech_stacks ?? []}
        disabled={disabled}
        onChange={(value) => onChange("techStack", value)}
      />

      <FilterSection label="Reward range">
        <div className="mt-2 grid grid-cols-2 gap-2">
          <RewardInput
            label="Minimum USDC"
            value={values.minReward}
            placeholder={facets ? String(facets.reward_range.min) : "Min"}
            disabled={disabled}
            onChange={(value) => onChange("minReward", value)}
          />
          <RewardInput
            label="Maximum USDC"
            value={values.maxReward}
            placeholder={facets ? String(facets.reward_range.max) : "Max"}
            disabled={disabled}
            onChange={(value) => onChange("maxReward", value)}
          />
        </div>
      </FilterSection>

      <FilterSelect
        label="Verification status"
        value={values.verification}
        options={facets?.verification_methods ?? []}
        disabled={disabled}
        onChange={(value) => onChange("verification", value)}
      />
      <FilterSelect
        label="Sort by"
        value={values.sort}
        options={SORT_OPTIONS.map((option) => option.value)}
        optionLabels={Object.fromEntries(SORT_OPTIONS.map((option) => [option.value, option.label]))}
        onChange={(value) => onChange("sort", value)}
      />

      {facetsFailed ? (
        <p className="mt-4 text-xs leading-5 text-veyra-muted-dark">Filter values are temporarily unavailable.</p>
      ) : null}
    </div>
  );
}

function FilterSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-veyra-cream/[0.08] py-4 last:border-b-0 last:pb-0">
      <p className="text-xs font-semibold uppercase tracking-[0.13em] text-veyra-muted-dark">{label}</p>
      {children}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  optionLabels,
  disabled = false,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  optionLabels?: Record<string, string>;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <FilterSection label={label}>
      <select
        value={value}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
        className={selectClass}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {optionLabels?.[option] ?? option}
          </option>
        ))}
      </select>
    </FilterSection>
  );
}

function RewardInput({
  label,
  value,
  placeholder,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <input
      type="number"
      min="0"
      step="1"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      aria-label={label}
      className="h-10 min-w-0 rounded-xl border border-veyra-cream/10 bg-veyra-ink px-3 text-sm text-veyra-cream outline-none placeholder:text-veyra-muted-dark focus-visible:border-veyra-sand/50 focus-visible:ring-2 focus-visible:ring-veyra-sand/20 disabled:cursor-not-allowed disabled:opacity-50"
    />
  );
}