import { apiFetch } from "@/lib/api";

/**
 * Public, read-only projection of an open Veyra job as returned by
 * `GET /api/v1/public/issues/`. These records are only the funded jobs that
 * are still OPEN for work. No repository credentials, verification secrets,
 * hidden acceptance data, drafts or private client records are ever included.
 */
export type PublicIssue = {
  reference: number;
  organisation: string;
  repository: string;
  repository_name: string;
  title: string;
  issue_number: number;
  task_type: string;
  labels: string[];
  tech_stack: string[];
  reward_usdc: string;
  deadline: string;
  verification_method: string;
  published_at: string;
  status: string;
  github_issue_url: string;
};

export type PublicIssueDetail = PublicIssue & {
  description: string;
  acceptance_overview: string[];
};

export type PublicIssueFacets = {
  total_open: number;
  projects: string[];
  task_types: string[];
  labels: string[];
  tech_stacks: string[];
  verification_methods: string[];
  reward_range: { min: number; max: number };
};

export type PaginatedIssues = {
  count: number;
  next: string | null;
  previous: string | null;
  results: PublicIssue[];
};

export type IssueSort = "newest" | "oldest" | "reward" | "deadline";

export type IssueQuery = {
  search?: string;
  project?: string;
  taskType?: string;
  label?: string;
  techStack?: string;
  minReward?: number;
  maxReward?: number;
  verification?: string;
  sort?: IssueSort;
  page?: number;
};

/** Fixed by the public API (page_size = 6). */
export const ISSUES_PER_PAGE = 6;

function buildQuery(query: IssueQuery): string {
  const params = new URLSearchParams();
  if (query.search) params.set("search", query.search);
  if (query.project) params.set("project", query.project);
  if (query.taskType) params.set("task_type", query.taskType);
  if (query.label) params.set("label", query.label);
  if (query.techStack) params.set("tech_stack", query.techStack);
  if (query.minReward !== undefined) params.set("min_reward", String(query.minReward));
  if (query.maxReward !== undefined) params.set("max_reward", String(query.maxReward));
  if (query.verification) params.set("verification", query.verification);
  if (query.sort) params.set("sort", query.sort);
  if (query.page && query.page > 1) params.set("page", String(query.page));
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function fetchPublicIssues(query: IssueQuery = {}): Promise<PaginatedIssues> {
  return apiFetch<PaginatedIssues>(`/api/v1/public/issues/${buildQuery(query)}`);
}

export function fetchPublicIssue(reference: number | string): Promise<PublicIssueDetail> {
  return apiFetch<PublicIssueDetail>(`/api/v1/public/issues/${reference}/`);
}

export function fetchPublicIssueFacets(): Promise<PublicIssueFacets> {
  return apiFetch<PublicIssueFacets>("/api/v1/public/issues/facets/");
}
