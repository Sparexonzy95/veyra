"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch, patchJson, postJson } from "@/lib/api";
import type {
  CircleChallengeResponse,
  CircleTransactionStatus,
  GitHubIssuePreview,
  JobDraft,
  RepositoryStackItem,
  TechnicalRequirement,
  VerificationMethod,
} from "@/types/veyra";
import {
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Github,
  GitPullRequest,
  Loader2,
  LockKeyhole,
  Plus,
  ShieldCheck,
  Trash2,
  Users,
  WalletCards,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

type Step = "details" | "review" | "funding" | "success";
type AgentAccess = "OPEN" | "INVITED";
type ValidationDetectionStatus =
  | "CONFIRMED"
  | "SUGGESTED"
  | "NEEDS_CONFIRMATION";

type CriterionRow = {
  id: string;
  text: string;
};

const selectClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

function rowId() {
  return Math.random().toString(36).slice(2, 10);
}

function toLocalInput(iso?: string) {
  const date = iso
    ? new Date(iso)
    : new Date(Date.now() + 2 * 24 * 60 * 60 * 1000);

  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

function newlineList(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatStack(item: RepositoryStackItem) {
  return item.version ? `${item.name} ${item.version}` : item.name;
}

function stackToRequirements(
  stack: RepositoryStackItem[],
): TechnicalRequirement[] {
  return stack
    .filter(
      (item) =>
        item.category !== "package_manager" &&
        item.category !== "styling" &&
        item.category !== "infrastructure",
    )
    .map((item) => ({
      name: item.name,
      version: item.version ?? "",
      category: item.category,
      level: "REQUIRED" as const,
    }));
}

function inferWorkType(title: string) {
  if (/\b(bug|fix|error|broken|regression)\b/i.test(title)) return "BUG_FIX";
  if (/\b(test|coverage)\b/i.test(title)) return "TESTING";
  if (/\b(document|docs|readme)\b/i.test(title)) return "DOCUMENTATION";
  if (/\b(refactor|cleanup|restructure)\b/i.test(title)) return "REFACTOR";
  if (/\b(security|vulnerability|audit)\b/i.test(title)) return "SECURITY";
  return "FEATURE";
}

function inferVerificationMethod(statement: string): VerificationMethod {
  const text = statement.toLowerCase();

  if (text.includes("pull request")) return "PULL_REQUEST_INSPECTION";
  if (
    text.includes("existing tests") ||
    text.includes("test suite") ||
    text.includes("all tests")
  ) {
    return "TEST_SUITE";
  }
  if (
    text.includes("do not change") ||
    text.includes("do not modify") ||
    text.includes("file")
  ) {
    return "FILE_INSPECTION";
  }
  return "AUTOMATED_TEST";
}

function criteriaToRows(criteria: string[]) {
  const rows = criteria.map((text) => ({ id: rowId(), text }));
  return rows.length ? rows : [{ id: rowId(), text: "" }];
}

function issueSummary(body: string) {
  const lines = body.split("\n");
  const summaryIndex = lines.findIndex(
    (line) => line.trim().toLowerCase() === "## summary",
  );
  const start = summaryIndex >= 0 ? summaryIndex + 1 : 0;
  const collected: string[] = [];

  for (let index = start; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (line.startsWith("#") && collected.length) break;
    if (!line || line.startsWith("#") || line.startsWith("```")) continue;
    collected.push(line);
    if (collected.join(" ").length > 420) break;
  }

  return collected.join(" ").slice(0, 500);
}

function shouldRetryApproval(error: unknown) {
  return (
    error instanceof Error &&
    error.message.toLowerCase().includes("approval has not been confirmed")
  );
}

function compactAddress(address?: string) {
  if (!address) return "Wallet connected";
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

export function CreateJobDialog({
  open,
  onOpenChange,
  initialDraft,
  onComplete,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialDraft?: JobDraft | null;
  onComplete: () => Promise<void> | void;
}) {
  const { circleToken, executeTrackedChallenge, me } = useVeyra();
  const [step, setStep] = useState<Step>("details");
  const [draft, setDraft] = useState<JobDraft | null>(null);
  const [preview, setPreview] = useState<GitHubIssuePreview | null>(null);

  const [githubUrl, setGithubUrl] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [jobType, setJobType] = useState("FEATURE");
  const [jobDescription, setJobDescription] = useState("");
  const [technicalRequirements, setTechnicalRequirements] = useState<
    TechnicalRequirement[]
  >([]);
  const [criteriaRows, setCriteriaRows] = useState<CriterionRow[]>([
    { id: rowId(), text: "" },
  ]);
  const [allowedPaths, setAllowedPaths] = useState("");
  const [forbiddenPaths, setForbiddenPaths] = useState("");
  const [requiredCommands, setRequiredCommands] = useState("");
  const [validationStatus, setValidationStatus] =
    useState<ValidationDetectionStatus>("NEEDS_CONFIRMATION");
  const [validationSource, setValidationSource] = useState("");
  const [validationConfirmed, setValidationConfirmed] = useState(false);
  const [editingValidation, setEditingValidation] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [deliveryType, setDeliveryType] = useState<"PULL_REQUEST" | "COMMIT">(
    "PULL_REQUEST",
  );
  const [agentAccess, setAgentAccess] = useState<AgentAccess>("OPEN");
  const [invitedAgent, setInvitedAgent] = useState("");
  const [budget, setBudget] = useState("1");
  const [deadline, setDeadline] = useState(toLocalInput());
  const [walletBalance, setWalletBalance] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [progressText, setProgressText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fundedJobId, setFundedJobId] = useState<number | null>(null);
  const [confirmedTransactionHash, setConfirmedTransactionHash] = useState("");

  const editable =
    !draft || draft.status === "DRAFT" || draft.status === "READY";
  const validCriteria = useMemo(
    () => criteriaRows.filter((item) => item.text.trim()),
    [criteriaRows],
  );
  const activeRequirements = technicalRequirements.filter((item) =>
    item.name.trim(),
  );
  const requiredSkills = activeRequirements.filter(
    (item) => item.level === "REQUIRED",
  );
  const numericBalance = walletBalance === null ? null : Number(walletBalance);
  const numericBudget = Number(budget || 0);
  const hasEnoughBalance =
    numericBalance !== null &&
    Number.isFinite(numericBalance) &&
    numericBalance >= numericBudget;
  const amountMissing =
    numericBalance !== null && Number.isFinite(numericBalance)
      ? Math.max(0, numericBudget - numericBalance)
      : null;

  useEffect(() => {
    if (!open) return;

    setError(null);
    setProgressText("");

    if (initialDraft) {
      const advanced = initialDraft.advanced_options ?? {};
      const stack = advanced.repository_stack ?? [];

      setDraft(initialDraft);
      setPreview({
        github_issue_url: initialDraft.github_issue_url,
        repository_owner: initialDraft.repository_owner,
        repository_name: initialDraft.repository_name,
        target_branch: initialDraft.target_branch,
        issue_number: initialDraft.issue_number,
        issue_title: initialDraft.issue_title,
        issue_body: initialDraft.issue_body,
        acceptance_criteria: initialDraft.acceptance_criteria,
        repository_stack: stack,
      });
      setGithubUrl(initialDraft.github_issue_url);
      setJobTitle(advanced.job_title ?? initialDraft.issue_title);
      setJobType(advanced.job_type ?? inferWorkType(initialDraft.issue_title));
      setJobDescription(
        advanced.job_description ?? initialDraft.issue_body ?? "",
      );
      setTechnicalRequirements(
        advanced.technical_requirements?.length
          ? advanced.technical_requirements
          : stackToRequirements(stack),
      );
      setCriteriaRows(criteriaToRows(initialDraft.acceptance_criteria));
      setAllowedPaths((advanced.allowed_paths ?? []).join("\n"));
      setForbiddenPaths((advanced.forbidden_paths ?? []).join("\n"));
      const savedCommands = advanced.required_commands ?? [];
      setRequiredCommands(savedCommands.join("\n"));
      setValidationStatus(
        savedCommands.length ? "CONFIRMED" : "NEEDS_CONFIRMATION",
      );
      setValidationSource(savedCommands.length ? "Saved with this job" : "");
      setValidationConfirmed(savedCommands.length > 0);
      setEditingValidation(savedCommands.length === 0);
      setAdvancedOpen(savedCommands.length === 0);
      setDeliveryType(advanced.delivery_type ?? "PULL_REQUEST");
      setInvitedAgent(advanced.invited_provider_address ?? "");
      setAgentAccess(
        advanced.invited_provider_address ? "INVITED" : "OPEN",
      );
      setBudget(initialDraft.budget_usdc);
      setDeadline(toLocalInput(initialDraft.deadline));
      setStep(initialDraft.status === "DRAFT" ? "details" : "review");
      return;
    }

    setDraft(null);
    setPreview(null);
    setGithubUrl("");
    setJobTitle("");
    setJobType("FEATURE");
    setJobDescription("");
    setTechnicalRequirements([]);
    setCriteriaRows([{ id: rowId(), text: "" }]);
    setAllowedPaths("");
    setForbiddenPaths("");
    setRequiredCommands("");
    setValidationStatus("NEEDS_CONFIRMATION");
    setValidationSource("");
    setValidationConfirmed(false);
    setEditingValidation(false);
    setAdvancedOpen(false);
    setDeliveryType("PULL_REQUEST");
    setAgentAccess("OPEN");
    setInvitedAgent("");
    setBudget("1");
    setDeadline(toLocalInput());
    setStep("details");
  }, [initialDraft, open]);

  useEffect(() => {
    if (!open || !circleToken) return;

    void apiFetch<{ balance: string }>("/api/v1/client/wallet/balance/", {
      circleUserToken: circleToken,
    })
      .then((result) => setWalletBalance(result.balance))
      .catch(() => setWalletBalance(null));
  }, [circleToken, open]);

  async function loadIssue() {
    setLoading(true);
    setError(null);

    try {
      const result = await postJson<GitHubIssuePreview>(
        "/api/v1/client/github/issue-preview/",
        { github_issue_url: githubUrl },
      );
      const stack = result.repository_stack ?? [];

      setPreview(result);
      setJobTitle(result.issue_title);
      setJobDescription(issueSummary(result.issue_body) || result.issue_body);
      setJobType(inferWorkType(result.issue_title));
      setTechnicalRequirements(stackToRequirements(stack));
      setCriteriaRows(criteriaToRows(result.acceptance_criteria));
      setAllowedPaths((result.suggested_allowed_paths ?? []).join("\n"));
      setForbiddenPaths("");
      const detection = result.validation_command_detection;
      const detectedCommands =
        detection?.commands?.length
          ? detection.commands
          : (result.suggested_required_commands ?? []);
      const detectedStatus: ValidationDetectionStatus =
        detection?.status ??
        (detectedCommands.length ? "SUGGESTED" : "NEEDS_CONFIRMATION");

      setRequiredCommands(detectedCommands.join("\n"));
      setValidationStatus(detectedStatus);
      setValidationSource(detection?.source ?? "");
      setValidationConfirmed(detectedStatus === "CONFIRMED");
      setEditingValidation(detectedStatus !== "CONFIRMED");
      setAdvancedOpen(detectedStatus !== "CONFIRMED");
      setDeliveryType("PULL_REQUEST");
      toast.success(
        detectedStatus === "CONFIRMED"
          ? "GitHub issue loaded. Veyra confirmed how the work will be checked."
          : "GitHub issue loaded. Review the suggested validation command.",
      );
    } catch (loadError) {
      setPreview(null);
      setError(
        loadError instanceof Error
          ? loadError.message
          : "GitHub issue could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }

  function updateRequirement(
    index: number,
    patch: Partial<TechnicalRequirement>,
  ) {
    setTechnicalRequirements((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    );
  }

  function updateCriterion(index: number, text: string) {
    setCriteriaRows((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, text } : item,
      ),
    );
  }

  function confirmValidationCommands() {
    if (!newlineList(requiredCommands).length) {
      setError("Add the command Veyra should run to check the completed work.");
      return;
    }

    setValidationConfirmed(true);
    setEditingValidation(false);
    setError(null);
    toast.success("Validation command confirmed.");
  }

  function validationError() {
    if (!preview) return "Load a public GitHub issue first.";
    if (!jobTitle.trim()) return "Add a clear job title.";
    if (!jobDescription.trim()) return "Add a short job description.";
    if (!requiredSkills.length) {
      return "Veyra needs at least one required skill to match a worker.";
    }
    if (!validCriteria.length) {
      return "Add at least one clear completion requirement.";
    }
    if (Number(budget) < 1) return "The minimum budget is 1 USDC.";
    if (
      !deadline ||
      new Date(deadline).getTime() <= Date.now() + 10 * 60 * 1000
    ) {
      return "Choose a deadline at least 10 minutes from now.";
    }
    if (!newlineList(requiredCommands).length) {
      return "Veyra could not detect how to check this job. Add a validation command in Advanced job settings.";
    }
    if (!validationConfirmed) {
      return "Confirm how Veyra should check the completed work in Advanced job settings.";
    }
    if (
      agentAccess === "INVITED" &&
      !/^0x[a-fA-F0-9]{40}$/.test(invitedAgent.trim())
    ) {
      return "Enter a valid invited worker wallet address.";
    }
    return null;
  }

  function draftPayload() {
    return {
      github_issue_url: githubUrl.trim(),
      budget_usdc: budget,
      deadline: new Date(deadline).toISOString(),
      acceptance_criteria: validCriteria.map((item) => item.text.trim()),
      advanced_options: {
        job_title: jobTitle.trim(),
        job_type: jobType,
        job_description: jobDescription.trim(),
        repository_stack: preview?.repository_stack ?? [],
        technical_requirements: activeRequirements.map((item) => ({
          ...item,
          name: item.name.trim(),
          version: item.version?.trim() ?? "",
        })),
        criterion_verification_methods: validCriteria.map((item) =>
          inferVerificationMethod(item.text),
        ),
        invited_provider_address:
          agentAccess === "INVITED" ? invitedAgent.trim() : "",
        allowed_paths: newlineList(allowedPaths),
        forbidden_paths: newlineList(forbiddenPaths),
        required_commands: newlineList(requiredCommands),
        delivery_type: deliveryType,
      },
    };
  }

  async function persistDraft() {
    const message = validationError();
    if (message) throw new Error(message);

    if (!draft) {
      return postJson<JobDraft>("/api/v1/client/job-drafts/", draftPayload());
    }
    if (!editable) return draft;

    return patchJson<JobDraft>(
      `/api/v1/client/job-drafts/${draft.id}/`,
      draftPayload(),
    );
  }

  async function saveDraft() {
    setLoading(true);
    setError(null);

    try {
      const current = await persistDraft();
      setDraft(current);
      toast.success("Job draft saved.");
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : "Draft could not be saved.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function reviewJob() {
    setLoading(true);
    setError(null);

    try {
      const current = await persistDraft();
      await postJson(`/api/v1/client/job-drafts/${current.id}/review/`, {});
      const updated = await apiFetch<JobDraft>(
        `/api/v1/client/job-drafts/${current.id}/`,
      );
      setDraft(updated);
      setStep("review");
    } catch (reviewError) {
      setError(
        reviewError instanceof Error
          ? reviewError.message
          : "Job could not be reviewed.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function requestFundingChallenge(draftId: string) {
    let lastError: unknown = null;

    for (let attempt = 0; attempt < 20; attempt += 1) {
      try {
        return await postJson<CircleChallengeResponse>(
          `/api/v1/client/job-drafts/${draftId}/funding-challenge/`,
          {},
          circleToken ?? undefined,
        );
      } catch (fundingError) {
        lastError = fundingError;
        if (!shouldRetryApproval(fundingError)) throw fundingError;
        setProgressText("Finalising the USDC approval on Arc…");
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
      }
    }

    throw lastError ?? new Error("USDC approval is still pending.");
  }

  async function waitForTransaction(
    transactionId: string,
    actionLabel: string,
  ): Promise<CircleTransactionStatus> {
    const failedStates = new Set([
      "FAILED",
      "DENIED",
      "EXPIRED",
      "EVENT_MISMATCH",
    ]);

    for (let attempt = 0; attempt < 120; attempt += 1) {
      const transaction = await apiFetch<CircleTransactionStatus>(
        `/api/v1/client/transactions/${transactionId}/`,
        { circleUserToken: circleToken ?? undefined },
      );

      if (transaction.status === "CONFIRMED") return transaction;

      if (failedStates.has(transaction.status)) {
        throw new Error(
          transaction.failure_message ||
            `${actionLabel} could not be confirmed. Please try again.`,
        );
      }

      if (transaction.status === "PENDING_ONCHAIN") {
        setProgressText(`${actionLabel} submitted. Waiting for Arc confirmation…`);
      } else if (transaction.status === "SUBMITTED") {
        setProgressText(`${actionLabel} submitted through Circle…`);
      } else if (transaction.status === "USER_APPROVAL_PENDING") {
        setProgressText(
          `Circle confirmed ${actionLabel.toLowerCase()}. Locating the submitted transaction…`,
        );
      } else if (transaction.status === "CHALLENGE_READY") {
        setProgressText("Waiting for Circle confirmation…");
      } else {
        setProgressText(`Preparing ${actionLabel.toLowerCase()}…`);
      }

      await new Promise((resolve) => window.setTimeout(resolve, 2500));
    }

    throw new Error(
      `${actionLabel} is taking longer than expected. It remains saved and can be checked again safely.`,
    );
  }

  async function fundJob() {
    if (!draft || !circleToken) {
      setError("Reconnect your secure wallet to fund this job.");
      return;
    }

    setStep("funding");
    setLoading(true);
    setError(null);
    setFundedJobId(null);
    setConfirmedTransactionHash("");

    try {
      setProgressText("Checking your USDC balance…");
      const balance = await apiFetch<{ balance: string }>(
        "/api/v1/client/wallet/balance/",
        { circleUserToken: circleToken },
      );

      if (Number(balance.balance) < Number(draft.budget_usdc)) {
        throw new Error(
          `You need ${draft.budget_usdc} USDC to fund this job. Current balance: ${balance.balance} USDC.`,
        );
      }

      setProgressText("Checking the job's USDC approval…");
      const approval = await postJson<
        CircleChallengeResponse & { approval_required: boolean }
      >(
        `/api/v1/client/job-drafts/${draft.id}/approval-challenge/`,
        {},
        circleToken,
      );

      if (approval.approval_required) {
        if (!approval.transaction_id) {
          throw new Error("Veyra could not create the approval transaction record.");
        }
        if (approval.requires_user_approval !== false) {
          if (!approval.challenge_id) {
            throw new Error("Circle did not return the USDC approval request.");
          }
          setProgressText(`Step 1 of 2: Confirm a ${draft.budget_usdc} USDC allowance in Circle.`);
          await executeTrackedChallenge(
            approval.challenge_id,
            approval.transaction_id,
          );
        }
        setProgressText("Verifying the USDC approval on Arc…");
        await waitForTransaction(approval.transaction_id, "USDC approval");
      }

      setProgressText("Preparing the escrow funding transaction…");
      const funding = await requestFundingChallenge(draft.id);
      if (!funding.transaction_id) {
        throw new Error("Veyra could not create the funding transaction record.");
      }

      if (funding.requires_user_approval !== false) {
        if (!funding.challenge_id) {
          throw new Error("Circle did not return the job funding request.");
        }
        setProgressText(`Step 2 of 2: Confirm funding of ${draft.budget_usdc} USDC in Circle.`);
        await executeTrackedChallenge(
          funding.challenge_id,
          funding.transaction_id,
        );
      }

      setProgressText("Verifying the funded job and locked terms on Arc…");
      const confirmed = await waitForTransaction(
        funding.transaction_id,
        "Job funding",
      );
      setFundedJobId(confirmed.job_id ?? null);
      setConfirmedTransactionHash(confirmed.arc_transaction_hash ?? "");
      setStep("success");
      await onComplete();
    } catch (fundError) {
      setStep("review");
      setError(
        fundError instanceof Error ? fundError.message : "Job funding failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function close() {
    await onComplete();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !loading && onOpenChange(next)}>
      <DialogContent className="max-h-[94vh] max-w-[980px] gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-5 pr-14">
          <DialogTitle>
            {step === "details"
              ? draft
                ? "Edit Job"
                : "Create Job"
              : step === "review"
                ? "Review Job"
                : step === "funding"
                  ? "Fund Job"
                  : "Job Funded"}
          </DialogTitle>
          <DialogDescription>
            {step === "details"
              ? "Tell Veyra what result you need. The technical details are prepared automatically from GitHub."
              : step === "review"
                ? "Confirm what the worker must deliver and what the verifier will check."
                : step === "funding"
                  ? "Complete the Circle confirmations to secure the job budget."
                  : "The job terms and escrow funding are confirmed on Arc Testnet."}
          </DialogDescription>
        </DialogHeader>

        {step === "details" ? (
          <div className="max-h-[calc(94vh-96px)] overflow-y-auto">
            <div className="space-y-5 p-6">
              <section className="rounded-xl border bg-card p-5 shadow-sm">
                <div className="flex items-center gap-2">
                  <Github className="h-4 w-4" />
                  <h3 className="font-semibold">1. GitHub task</h3>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Paste a public GitHub issue. Veyra will read the repository,
                  task and testing setup.
                </p>

                <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                  <Input
                    aria-label="GitHub Issue URL"
                    placeholder="https://github.com/owner/repository/issues/1"
                    value={githubUrl}
                    onChange={(event) => setGithubUrl(event.target.value)}
                  />
                  <Button
                    variant="outline"
                    onClick={() => void loadIssue()}
                    disabled={!githubUrl.trim() || loading}
                    className="shrink-0"
                  >
                    {loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Github className="h-4 w-4" />
                    )}
                    Load Issue
                  </Button>
                </div>

                {preview ? (
                  <div className="mt-4 rounded-lg border bg-muted/20 p-4">
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                      <div>
                        <p className="font-medium">
                          {preview.repository_owner}/{preview.repository_name}
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          Issue #{preview.issue_number} · {preview.issue_state ?? "open"} · {preview.target_branch}
                        </p>
                      </div>
                      <span className="flex items-center gap-1 text-sm font-medium text-green-700 dark:text-green-300">
                        <CheckCircle2 className="h-4 w-4" /> Ready
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(preview.repository_stack ?? []).map((item) => (
                        <Badge
                          key={`${item.name}-${item.version}`}
                          variant="outline"
                        >
                          {formatStack(item)}
                        </Badge>
                      ))}
                    </div>
                    <div className="mt-4 flex flex-col gap-2 border-t pt-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="font-medium">How the result will be checked</p>
                        <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                          {newlineList(requiredCommands).join(" · ") || "Not detected"}
                        </p>
                      </div>
                      {validationConfirmed ? (
                        <span className="flex items-center gap-1 font-medium text-green-700 dark:text-green-300">
                          <CheckCircle2 className="h-4 w-4" /> Detected automatically
                        </span>
                      ) : (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setAdvancedOpen(true)}
                        >
                          Review command
                        </Button>
                      )}
                    </div>
                  </div>
                ) : null}
              </section>

              <section className="rounded-xl border bg-card p-5 shadow-sm">
                <h3 className="font-semibold">2. What needs to be done?</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Keep this clear and outcome-focused. Veyra fills it from the
                  issue, and you can correct it before publishing.
                </p>

                <div className="mt-4 grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="job-title">Job title</Label>
                    <Input
                      id="job-title"
                      value={jobTitle}
                      onChange={(event) => setJobTitle(event.target.value)}
                      placeholder="Describe the expected result"
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="job-description">Job description</Label>
                    <Textarea
                      id="job-description"
                      rows={4}
                      value={jobDescription}
                      onChange={(event) => setJobDescription(event.target.value)}
                      placeholder="Explain the result you need and any important context."
                    />
                  </div>
                </div>
              </section>

              <section className="rounded-xl border bg-card p-5 shadow-sm">
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                  <div>
                    <h3 className="font-semibold">3. What must be completed?</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Each item should be a result the verifier can clearly
                      mark as passed or failed.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setCriteriaRows((current) => [
                        ...current,
                        { id: rowId(), text: "" },
                      ])
                    }
                  >
                    <Plus className="h-4 w-4" />
                    Add requirement
                  </Button>
                </div>

                <div className="mt-4 space-y-3">
                  {criteriaRows.map((criterion, index) => (
                    <div
                      key={criterion.id}
                      className="flex items-start gap-3 rounded-lg border bg-muted/10 p-3"
                    >
                      <div className="mt-2 flex h-5 w-5 shrink-0 items-center justify-center rounded border text-xs text-muted-foreground">
                        {index + 1}
                      </div>
                      <Textarea
                        aria-label={`Completion requirement ${index + 1}`}
                        rows={2}
                        value={criterion.text}
                        onChange={(event) =>
                          updateCriterion(index, event.target.value)
                        }
                        placeholder="State one clear, verifiable result"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Remove requirement"
                        disabled={criteriaRows.length === 1}
                        onClick={() =>
                          setCriteriaRows((current) =>
                            current.filter((item) => item.id !== criterion.id),
                          )
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              </section>

              <section className="rounded-xl border bg-card p-5 shadow-sm">
                <h3 className="font-semibold">4. Payment and deadline</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Payment is secured in USDC on Arc Testnet and released only
                  after independent verification.
                </p>

                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div className="grid gap-2">
                    <Label htmlFor="budget">Budget</Label>
                    <div className="relative">
                      <Input
                        id="budget"
                        type="number"
                        min="1"
                        step="0.01"
                        value={budget}
                        onChange={(event) => setBudget(event.target.value)}
                        className="pr-16"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                        USDC
                      </span>
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="deadline">Deadline</Label>
                    <Input
                      id="deadline"
                      type="datetime-local"
                      value={deadline}
                      onChange={(event) => setDeadline(event.target.value)}
                    />
                  </div>
                </div>

                <div className="mt-4 rounded-lg border bg-muted/20 p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-muted-foreground">Wallet balance</span>
                    <span className="font-medium">
                      {walletBalance === null ? "Checking…" : `${walletBalance} USDC`}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-muted-foreground">Wallet</span>
                    <span className="font-medium">
                      {compactAddress(me?.wallet?.address)}
                    </span>
                  </div>
                  {amountMissing !== null && amountMissing > 0 ? (
                    <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                      You need {amountMissing.toFixed(2)} more USDC to fund this job.
                    </p>
                  ) : null}
                </div>
              </section>

              <section className="rounded-xl border bg-card p-5 shadow-sm">
                <div className="flex items-center gap-2">
                  <Users className="h-4 w-4" />
                  <h3 className="font-semibold">5. Who can work on this job?</h3>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => setAgentAccess("OPEN")}
                    className={`rounded-lg border p-4 text-left transition-colors ${
                      agentAccess === "OPEN"
                        ? "border-primary bg-primary/5"
                        : "hover:bg-muted/40"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-4 w-4 rounded-full border ${
                          agentAccess === "OPEN"
                            ? "border-[5px] border-primary"
                            : "border-muted-foreground"
                        }`}
                      />
                      <span className="font-medium">Open marketplace</span>
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                      Any authorised worker that matches the required skills may
                      claim it.
                    </p>
                  </button>

                  <button
                    type="button"
                    onClick={() => setAgentAccess("INVITED")}
                    className={`rounded-lg border p-4 text-left transition-colors ${
                      agentAccess === "INVITED"
                        ? "border-primary bg-primary/5"
                        : "hover:bg-muted/40"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-4 w-4 rounded-full border ${
                          agentAccess === "INVITED"
                            ? "border-[5px] border-primary"
                            : "border-muted-foreground"
                        }`}
                      />
                      <span className="font-medium">Invite one worker</span>
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                      Only the selected authorised worker may claim it.
                    </p>
                  </button>
                </div>

                {agentAccess === "INVITED" ? (
                  <div className="mt-4 grid gap-2">
                    <Label htmlFor="invited-agent">Worker wallet address</Label>
                    <Input
                      id="invited-agent"
                      placeholder="0x…"
                      value={invitedAgent}
                      onChange={(event) => setInvitedAgent(event.target.value)}
                    />
                  </div>
                ) : null}
              </section>

              <details
                className="group rounded-xl border bg-card shadow-sm"
                open={advancedOpen}
                onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-5">
                  <div>
                    <h3 className="font-semibold">Advanced job settings</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Veyra prepared these from the repository. Change them only
                      when the issue requires something different.
                    </p>
                  </div>
                  <ChevronDown className="h-5 w-5 transition-transform group-open:rotate-180" />
                </summary>

                <div className="space-y-6 border-t p-5">
                  <div>
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                      <div>
                        <Label>Skills workers must have</Label>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Used to decide whether a worker is qualified to claim.
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setTechnicalRequirements((current) => [
                            ...current,
                            {
                              name: "",
                              version: "",
                              category: "tooling",
                              level: "REQUIRED",
                            },
                          ])
                        }
                      >
                        <Plus className="h-4 w-4" /> Add skill
                      </Button>
                    </div>

                    <div className="mt-3 space-y-2">
                      {technicalRequirements.map((requirement, index) => (
                        <div
                          key={`${requirement.name}-${index}`}
                          className="grid gap-2 rounded-lg border p-3 sm:grid-cols-[minmax(0,1fr)_120px_130px_36px]"
                        >
                          <Input
                            aria-label="Skill"
                            placeholder="Python"
                            value={requirement.name}
                            onChange={(event) =>
                              updateRequirement(index, {
                                name: event.target.value,
                              })
                            }
                          />
                          <Input
                            aria-label="Version"
                            placeholder="Version"
                            value={requirement.version ?? ""}
                            onChange={(event) =>
                              updateRequirement(index, {
                                version: event.target.value,
                              })
                            }
                          />
                          <select
                            aria-label="Requirement level"
                            className={selectClass}
                            value={requirement.level}
                            onChange={(event) =>
                              updateRequirement(index, {
                                level: event.target.value as
                                  | "REQUIRED"
                                  | "PREFERRED",
                              })
                            }
                          >
                            <option value="REQUIRED">Required</option>
                            <option value="PREFERRED">Preferred</option>
                          </select>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label="Remove skill"
                            onClick={() =>
                              setTechnicalRequirements((current) =>
                                current.filter(
                                  (_, itemIndex) => itemIndex !== index,
                                ),
                              )
                            }
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="grid gap-2">
                      <Label htmlFor="allowed-paths">Files the worker may change</Label>
                      <Textarea
                        id="allowed-paths"
                        rows={4}
                        value={allowedPaths}
                        onChange={(event) => setAllowedPaths(event.target.value)}
                        placeholder={"Leave blank for repository-wide access\nOne path per line"}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="forbidden-paths">Protected files</Label>
                      <Textarea
                        id="forbidden-paths"
                        rows={4}
                        value={forbiddenPaths}
                        onChange={(event) => setForbiddenPaths(event.target.value)}
                        placeholder={"Files the worker must not change\nOne path per line"}
                      />
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="grid gap-2">
                      <Label htmlFor="required-commands">
                        How the result will be checked
                      </Label>

                      {!editingValidation && validationConfirmed ? (
                        <div className="rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950/30">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="flex items-center gap-2 text-sm font-medium text-green-800 dark:text-green-200">
                                <CheckCircle2 className="h-4 w-4" />
                                Detected automatically
                              </p>
                              <p className="mt-2 whitespace-pre-line font-mono text-xs">
                                {newlineList(requiredCommands).join("\n")}
                              </p>
                              {validationSource ? (
                                <p className="mt-2 text-xs text-green-700/80 dark:text-green-300/80">
                                  Source: {validationSource}
                                </p>
                              ) : null}
                            </div>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => setEditingValidation(true)}
                            >
                              Change command
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/30">
                          <p className="text-sm font-medium text-amber-900 dark:text-amber-100">
                            {validationStatus === "SUGGESTED"
                              ? "Veyra found a likely command. Confirm it before publishing."
                              : "Veyra could not confirm the command automatically."}
                          </p>
                          {validationSource ? (
                            <p className="mt-1 text-xs text-amber-800/80 dark:text-amber-200/80">
                              {validationSource}
                            </p>
                          ) : null}
                          <Textarea
                            id="required-commands"
                            className="mt-3 bg-background"
                            rows={3}
                            value={requiredCommands}
                            onChange={(event) => {
                              setRequiredCommands(event.target.value);
                              setValidationConfirmed(false);
                            }}
                            placeholder={"Example: pytest"}
                          />
                          <Button
                            type="button"
                            size="sm"
                            className="mt-3"
                            onClick={confirmValidationCommands}
                          >
                            Confirm command
                          </Button>
                        </div>
                      )}
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="delivery-type">Required delivery</Label>
                      <select
                        id="delivery-type"
                        className={selectClass}
                        value={deliveryType}
                        onChange={(event) =>
                          setDeliveryType(
                            event.target.value as "PULL_REQUEST" | "COMMIT",
                          )
                        }
                      >
                        <option value="PULL_REQUEST">
                          Pull request against {preview?.target_branch ?? "main"}
                        </option>
                        <option value="COMMIT">Commit hash</option>
                      </select>
                    </div>
                  </div>

                  <div className="rounded-lg border bg-muted/20 p-4 text-sm">
                    <p className="font-medium">What the worker and verifier receive</p>
                    <p className="mt-1 text-muted-foreground">
                      The repository, required skills, completion checklist,
                      allowed and protected files, validation commands, target
                      branch, deadline and budget are locked together when the
                      job is funded.
                    </p>
                  </div>
                </div>
              </details>

              {error ? (
                <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  {error}
                </p>
              ) : null}
            </div>

            <div className="sticky bottom-0 flex flex-col-reverse justify-end gap-3 border-t bg-background/95 px-6 py-4 backdrop-blur sm:flex-row">
              <Button
                variant="outline"
                onClick={() => void saveDraft()}
                disabled={loading}
              >
                Save Draft
              </Button>
              <Button onClick={() => void reviewJob()} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Review Job
              </Button>
            </div>
          </div>
        ) : null}

        {step === "review" && draft ? (
          <div className="max-h-[calc(94vh-96px)] overflow-y-auto">
            <div className="grid gap-5 p-6 lg:grid-cols-[minmax(0,1fr)_290px]">
              <div className="space-y-5">
                <section className="rounded-xl border p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-xl font-semibold">{jobTitle}</h3>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {draft.repository_owner}/{draft.repository_name} · Issue #{draft.issue_number}
                      </p>
                    </div>
                    <Github className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <p className="mt-5 whitespace-pre-wrap text-sm leading-6">
                    {jobDescription}
                  </p>
                </section>

                <section className="rounded-xl border p-5">
                  <h3 className="font-semibold">What must be completed</h3>
                  <div className="mt-4 space-y-3">
                    {validCriteria.map((item) => (
                      <div key={item.id} className="flex items-start gap-3">
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                        <p className="text-sm">{item.text}</p>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="rounded-xl border p-5">
                  <h3 className="font-semibold">Worker and verification setup</h3>
                  <div className="mt-4 grid gap-5 text-sm sm:grid-cols-2">
                    <div>
                      <p className="text-muted-foreground">Required skills</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {requiredSkills.map((item, index) => (
                          <Badge key={`${item.name}-${index}`} variant="outline">
                            {item.name}{item.version ? ` ${item.version}` : ""}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="text-muted-foreground">How the result will be checked</p>
                      <p className="mt-2 whitespace-pre-line font-mono text-xs">
                        {newlineList(requiredCommands).join("\n")}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Files the worker may change</p>
                      <p className="mt-2 whitespace-pre-line font-medium">
                        {newlineList(allowedPaths).join("\n") || "Repository-wide"}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Required delivery</p>
                      <p className="mt-2 font-medium">
                        {deliveryType === "PULL_REQUEST"
                          ? `Pull request against ${draft.target_branch}`
                          : "Commit hash"}
                      </p>
                    </div>
                  </div>
                </section>
              </div>

              <aside className="space-y-4">
                <section className="rounded-xl border p-5">
                  <div className="flex items-center gap-2">
                    <WalletCards className="h-4 w-4" />
                    <h3 className="font-semibold">Payment</h3>
                  </div>
                  <dl className="mt-4 space-y-4 text-sm">
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted-foreground">Budget</dt>
                      <dd className="font-semibold">{draft.budget_usdc} USDC</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted-foreground">Wallet balance</dt>
                      <dd className="font-medium">
                        {walletBalance ?? "—"} USDC
                      </dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted-foreground">Deadline</dt>
                      <dd className="text-right font-medium">
                        {new Date(draft.deadline).toLocaleString()}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted-foreground">Who can claim</dt>
                      <dd className="text-right font-medium">
                        {agentAccess === "OPEN"
                          ? "Qualified workers"
                          : "Invited worker"}
                      </dd>
                    </div>
                  </dl>

                  {!hasEnoughBalance && amountMissing !== null ? (
                    <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                      Add {amountMissing.toFixed(2)} USDC to this wallet before funding.
                    </p>
                  ) : null}
                </section>

                <section className="rounded-xl border p-5">
                  <h3 className="font-semibold">Ready to publish</h3>
                  <div className="mt-4 space-y-3 text-sm">
                    {[
                      "GitHub issue loaded",
                      "Completion requirements provided",
                      "Worker skills identified",
                      "Verification command provided",
                      "Deadline and budget confirmed",
                    ].map((label) => (
                      <div
                        key={label}
                        className="flex items-center justify-between gap-3"
                      >
                        <span className="text-muted-foreground">{label}</span>
                        <Check className="h-4 w-4 text-green-700 dark:text-green-300" />
                      </div>
                    ))}
                  </div>
                </section>

                <div className="flex items-start gap-3 rounded-lg border bg-muted/30 p-4">
                  <ShieldCheck className="mt-0.5 h-5 w-5 text-primary" />
                  <div>
                    <p className="font-medium">Payment protection</p>
                    <p className="text-sm text-muted-foreground">
                      Funds remain locked until the work passes independent
                      verification.
                    </p>
                  </div>
                </div>
              </aside>
            </div>

            {error ? (
              <p className="mx-6 mb-5 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {error}
              </p>
            ) : null}

            <div className="sticky bottom-0 flex flex-col-reverse justify-end gap-3 border-t bg-background/95 px-6 py-4 backdrop-blur sm:flex-row">
              {editable ? (
                <Button variant="outline" onClick={() => setStep("details")}>
                  Back to Edit
                </Button>
              ) : null}
              <Button
                onClick={() => void fundJob()}
                disabled={loading || !hasEnoughBalance}
              >
                <LockKeyhole className="h-4 w-4" />
                {hasEnoughBalance ? "Approve & Fund Job" : "Insufficient USDC"}
              </Button>
            </div>
          </div>
        ) : null}

        {step === "funding" ? (
          <div className="flex flex-col items-center justify-center gap-5 py-16 text-center">
            <div className="rounded-full bg-primary/10 p-4 text-primary">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
            <div>
              <h3 className="text-lg font-semibold">Funding your job…</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                {progressText}
              </p>
            </div>
          </div>
        ) : null}

        {step === "success" ? (
          <div className="flex flex-col items-center justify-center gap-5 py-14 text-center">
            <div className="rounded-full bg-green-50 p-4 text-green-700 dark:bg-green-950/40 dark:text-green-300">
              <GitPullRequest className="h-9 w-9" />
            </div>
            <div>
              <h3 className="text-xl font-semibold">Job funded and open</h3>
              <p className="mt-2 max-w-md text-sm text-muted-foreground">
                Arc confirmed the escrow funding and Veyra verified the exact
                JobCreated event against the locked job terms.
              </p>
              {fundedJobId !== null ? (
                <p className="mt-3 text-sm font-medium">Job #{fundedJobId}</p>
              ) : null}
              {confirmedTransactionHash ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Transaction {confirmedTransactionHash.slice(0, 10)}…{confirmedTransactionHash.slice(-8)}
                </p>
              ) : null}
            </div>
            <Button onClick={() => void close()}>Back to Jobs</Button>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}