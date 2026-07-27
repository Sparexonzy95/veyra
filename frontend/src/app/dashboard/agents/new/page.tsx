"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { postJson } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  AgentSpecialisation,
  AgentSummary,
  CreateAgentPayload,
} from "@/types/veyra";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  Loader2,
  Link2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

const specialisations: Array<{ value: AgentSpecialisation; label: string; description: string }> = [
  { value: "PYTHON_BACKEND", label: "Python Backend Agent", description: "APIs, services, data logic, and backend tests." },
  { value: "JAVASCRIPT_FRONTEND", label: "JavaScript Frontend Agent", description: "React, Next.js, UI fixes, and browser tests." },
  { value: "FULL_STACK_WEB", label: "Full-Stack Web Agent", description: "Coordinated frontend and backend web changes." },
  { value: "SMART_CONTRACT", label: "Smart Contract Agent", description: "Solidity contracts, tests, and protocol integrations." },
  { value: "TESTING_QA", label: "Testing and QA Agent", description: "Regression tests, test repair, and quality checks." },
  { value: "DOCUMENTATION", label: "Documentation Agent", description: "Technical guides, API docs, and repository documentation." },
];

const catalog = {
  languages: ["Python", "TypeScript", "JavaScript", "Solidity", "Rust", "SQL"],
  frameworks: ["Flask", "Django", "FastAPI", "React", "Next.js", "Node.js", "Express", "Hardhat", "Foundry"],
  testing_tools: ["Pytest", "unittest", "Jest", "Vitest", "Playwright", "Hardhat Test", "Foundry Test"],
  task_types: ["API endpoint", "Bug fix", "Automated tests", "Frontend component", "Smart contract", "Documentation"],
};

const limits = {
  languages: 2,
  frameworks: 3,
  testing_tools: 2,
  task_types: 3,
};

type CapabilityKey = keyof typeof catalog;

const initialForm: CreateAgentPayload = {
  connection_link: "",
  name: "",
  description: "",
  avatar_url: "",
  specialisation: "PYTHON_BACKEND",
  languages: [],
  frameworks: [],
  testing_tools: [],
  task_types: [],
  minimum_budget_usdc: "1.000000",
  maximum_budget_usdc: "5.000000",
  public_repositories_only: true,
  allowed_organizations: [],
  maximum_active_jobs: 1,
  maximum_execution_minutes: 45,
  allow_fork_creation: false,
  allow_new_dependencies: false,
  allow_database_migrations: false,
  protected_paths: [".env", ".github/workflows"],
};

const steps = [
  { title: "Identity", icon: Bot },
  { title: "Capabilities", icon: Sparkles },
  { title: "Work Policy", icon: SlidersHorizontal },
  { title: "Connect Agent", icon: Link2 },
  { title: "Review", icon: ShieldCheck },
];

function CapabilityPicker({
  title,
  help,
  field,
  selected,
  onChange,
}: {
  title: string;
  help: string;
  field: CapabilityKey;
  selected: string[];
  onChange: (items: string[]) => void;
}) {
  function toggle(item: string) {
    if (selected.includes(item)) {
      onChange(selected.filter((value) => value !== item));
      return;
    }
    if (selected.length >= limits[field]) {
      toast.error(`${title} allows a maximum of ${limits[field]}.`);
      return;
    }
    onChange([...selected, item]);
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center justify-between gap-4">
          <Label>{title}</Label>
          <span className="text-xs text-muted-foreground">
            {selected.length}/{limits[field]}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{help}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {catalog[field].map((item) => {
          const active = selected.includes(item);
          return (
            <button
              key={item}
              type="button"
              onClick={() => toggle(item)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-sm transition-colors",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-background hover:border-primary/50 hover:bg-muted",
              )}
            >
              {active ? <Check className="mr-1 inline h-3.5 w-3.5" /> : null}
              {item}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PolicyToggle({
  checked,
  onChange,
  title,
  description,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: string;
  description: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 hover:bg-muted/40">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 accent-primary"
      />
      <span>
        <span className="block text-sm font-medium">{title}</span>
        <span className="mt-1 block text-xs text-muted-foreground">{description}</span>
      </span>
    </label>
  );
}

export default function CreateAgentPage() {
  const router = useRouter();
  const { me, refreshMe } = useVeyra();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<CreateAgentPayload>(initialForm);
  const [organizationsText, setOrganizationsText] = useState("");
  const [protectedPathsText, setProtectedPathsText] = useState(".env\n.github/workflows");
  const [saving, setSaving] = useState(false);

  const capabilityCount = useMemo(
    () =>
      form.languages.length +
      form.frameworks.length +
      form.testing_tools.length +
      form.task_types.length,
    [form],
  );

  function update<K extends keyof CreateAgentPayload>(key: K, value: CreateAgentPayload[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function validateCurrentStep() {
    if (step === 0) {
      if (form.name.trim().length < 3) {
        toast.error("Give the agent a name with at least three characters.");
        return false;
      }
      if (form.description.trim().length < 12) {
        toast.error("Add a clear one-sentence agent description.");
        return false;
      }
    }
    if (step === 1) {
      if (!capabilityCount) {
        toast.error("Select at least one focused capability.");
        return false;
      }
      if (capabilityCount > 10) {
        toast.error("Keep the profile focused to ten capability tags or fewer.");
        return false;
      }
    }
    if (step === 2) {
      const minimum = Number(form.minimum_budget_usdc);
      const maximum = Number(form.maximum_budget_usdc);
      if (!Number.isFinite(minimum) || minimum <= 0) {
        toast.error("Minimum budget must be greater than zero.");
        return false;
      }
      if (!Number.isFinite(maximum) || maximum < minimum) {
        toast.error("Maximum budget must be at least the minimum budget.");
        return false;
      }
    }
    if (step === 3) {
      if (!form.connection_link.trim().startsWith("veyra-connect://")) {
        toast.error("Paste the connection URL generated by your Agent Starter.");
        return false;
      }
    }
    return true;
  }

  function next() {
    if (!validateCurrentStep()) return;
    setStep((current) => Math.min(current + 1, steps.length - 1));
  }

  async function createAgent() {
    if (!validateCurrentStep()) return;
    setSaving(true);
    try {
      // Existing client accounts may add the Agent Owner workspace later.
      // Grant that owner-scoped capability before calling the protected agent API.
      if (!me?.capabilities?.includes("AGENT_OWNER")) {
        await postJson("/api/v1/onboarding/agent-owner/", {
          notification_email: me?.user?.email ?? "",
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        });
        await refreshMe();
      }

      const payload: CreateAgentPayload = {
        ...form,
        name: form.name.trim(),
        description: form.description.trim(),
        avatar_url: form.avatar_url?.trim() || "",
        allowed_organizations: organizationsText
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        protected_paths: protectedPathsText
          .split(/\r?\n/)
          .map((item) => item.trim())
          .filter(Boolean),
      };
      const agent = await postJson<AgentSummary>("/api/v1/agents/", payload);
      if (agent.provisioning_error) {
        toast.error(`Agent saved, but activation needs attention: ${agent.provisioning_error}`);
      } else {
        toast.success("Hosted brain connected, wallet created, and contract authorisation completed.");
      }
      router.push(`/dashboard/agents/${agent.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Agent could not be created.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Create an Agent</h1>
        <p className="text-muted-foreground">
          Configure the Agent Starter, host and start it, then paste its connection URL. Veyra handles
          the dedicated wallet and contract authorisation automatically.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {steps.map((item, index) => {
          const Icon = item.icon;
          const active = step === index;
          const complete = step > index;
          return (
            <button
              key={item.title}
              type="button"
              onClick={() => complete && setStep(index)}
              className={cn(
                "flex items-center gap-3 rounded-xl border p-3 text-left",
                active && "border-primary bg-primary/5",
                complete && "cursor-pointer border-primary/30",
              )}
            >
              <span
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-lg bg-muted",
                  (active || complete) && "bg-primary text-primary-foreground",
                )}
              >
                {complete ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </span>
              <span>
                <span className="block text-xs text-muted-foreground">Step {index + 1}</span>
                <span className="block text-sm font-medium">{item.title}</span>
              </span>
            </button>
          );
        })}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{steps[step].title}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {step === 0 ? (
            <>
              <div className="grid gap-5 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="name">Agent name</Label>
                  <Input
                    id="name"
                    value={form.name}
                    onChange={(event) => update("name", event.target.value)}
                    placeholder="LogicBloom Flask Agent"
                    maxLength={160}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="specialisation">Primary specialisation</Label>
                  <Select
                    value={form.specialisation}
                    onValueChange={(value) => update("specialisation", value as AgentSpecialisation)}
                  >
                    <SelectTrigger id="specialisation">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {specialisations.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Short description</Label>
                <Textarea
                  id="description"
                  value={form.description}
                  onChange={(event) => update("description", event.target.value)}
                  placeholder="Builds and tests Flask API endpoints."
                  rows={4}
                  maxLength={600}
                />
                <p className="text-xs text-muted-foreground">
                  Describe what the agent actually does—not what every coding agent could do.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="avatar">Avatar URL (optional)</Label>
                <Input
                  id="avatar"
                  type="url"
                  value={form.avatar_url}
                  onChange={(event) => update("avatar_url", event.target.value)}
                  placeholder="https://..."
                />
              </div>
              <div className="rounded-xl border bg-muted/40 p-4 text-sm">
                <p className="font-medium">
                  {specialisations.find((item) => item.value === form.specialisation)?.label}
                </p>
                <p className="mt-1 text-muted-foreground">
                  {specialisations.find((item) => item.value === form.specialisation)?.description}
                </p>
              </div>
            </>
          ) : null}

          {step === 1 ? (
            <>
              <div className="flex items-center justify-between rounded-xl border bg-muted/30 p-4">
                <div>
                  <p className="font-medium">Keep the profile focused</p>
                  <p className="text-sm text-muted-foreground">
                    Veyra matches jobs from these capability tags. Quality beats a giant list.
                  </p>
                </div>
                <Badge variant={capabilityCount > 10 ? "destructive" : "outline"}>
                  {capabilityCount}/10 total
                </Badge>
              </div>
              <CapabilityPicker
                title="Languages"
                help="Select no more than two languages the owner-hosted agent actually supports."
                field="languages"
                selected={form.languages}
                onChange={(items) => update("languages", items)}
              />
              <CapabilityPicker
                title="Frameworks"
                help="Choose up to three frameworks that define the agent's real speciality."
                field="frameworks"
                selected={form.frameworks}
                onChange={(items) => update("frameworks", items)}
              />
              <CapabilityPicker
                title="Testing tools"
                help="Choose up to two test tools the owner-hosted agent should use."
                field="testing_tools"
                selected={form.testing_tools}
                onChange={(items) => update("testing_tools", items)}
              />
              <CapabilityPicker
                title="Task types"
                help="Choose no more than three job types the agent should receive."
                field="task_types"
                selected={form.task_types}
                onChange={(items) => update("task_types", items)}
              />
            </>
          ) : null}

          {step === 2 ? (
            <>
              <div className="grid gap-5 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="min-budget">Minimum budget (USDC)</Label>
                  <Input
                    id="min-budget"
                    type="number"
                    min="0.000001"
                    step="0.000001"
                    value={form.minimum_budget_usdc}
                    onChange={(event) => update("minimum_budget_usdc", event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="max-budget">Maximum budget (USDC)</Label>
                  <Input
                    id="max-budget"
                    type="number"
                    min="0.000001"
                    step="0.000001"
                    value={form.maximum_budget_usdc}
                    onChange={(event) => update("maximum_budget_usdc", event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Maximum concurrent jobs</Label>
                  <Select
                    value={String(form.maximum_active_jobs)}
                    onValueChange={(value) => update("maximum_active_jobs", Number(value))}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {[1, 2, 3].map((value) => (
                        <SelectItem key={value} value={String(value)}>{value}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Maximum execution time</Label>
                  <Select
                    value={String(form.maximum_execution_minutes)}
                    onValueChange={(value) => update("maximum_execution_minutes", Number(value))}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {[30, 45, 60, 90, 120, 180].map((value) => (
                        <SelectItem key={value} value={String(value)}>{value} minutes</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="organizations">Allowed GitHub organisations</Label>
                <Input
                  id="organizations"
                  value={organizationsText}
                  onChange={(event) => setOrganizationsText(event.target.value)}
                  placeholder="Leave blank for any permitted public organisation"
                />
                <p className="text-xs text-muted-foreground">
                  Separate multiple organisations with commas.
                </p>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <PolicyToggle
                  checked={form.public_repositories_only}
                  onChange={(checked) => update("public_repositories_only", checked)}
                  title="Public repositories only"
                  description="Recommended for the MVP and judge testing flow."
                />
                <PolicyToggle
                  checked={form.allow_new_dependencies}
                  onChange={(checked) => update("allow_new_dependencies", checked)}
                  title="Allow new dependencies"
                  description="Permit dependency-file changes when the task requires them."
                />
                <PolicyToggle
                  checked={form.allow_database_migrations}
                  onChange={(checked) => update("allow_database_migrations", checked)}
                  title="Allow database migrations"
                  description="Permit migration files only for matching jobs."
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="protected-paths">Protected paths</Label>
                <Textarea
                  id="protected-paths"
                  value={protectedPathsText}
                  onChange={(event) => setProtectedPathsText(event.target.value)}
                  rows={5}
                  placeholder={".env\n.github/workflows"}
                />
                <p className="text-xs text-muted-foreground">One repository path per line.</p>
              </div>

              <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
                The owner pays for AI usage and hosting. Veyra never receives the provider API key.
                Auto-claim stays off until qualification passes.
              </div>
            </>
          ) : null}

          {step === 3 ? (
            <div className="space-y-6">
              <div className="rounded-xl border bg-muted/30 p-5">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <Link2 className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="font-medium">Connect Agent</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Download the Agent Starter, add your provider API key and model, host and start it,
                      then paste its Veyra connection URL below. The paid AI key remains on that server.
                    </p>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="connection-link">Agent Starter connection URL</Label>
                <Textarea
                  id="connection-link"
                  value={form.connection_link}
                  onChange={(event) => update("connection_link", event.target.value.trim())}
                  placeholder="veyra-connect://localhost:9100/connect/one-time-token?protocol=1"
                  rows={4}
                  spellCheck={false}
                  className="font-mono text-xs"
                />
                <p className="text-xs text-muted-foreground">
                  This one-time link contains the server address and a temporary claim token. It does not contain the AI API key.
                </p>
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-xl border p-4">
                  <p className="text-sm font-medium">1. Verify server</p>
                  <p className="mt-1 text-xs text-muted-foreground">Veyra sends a signed challenge to prove ownership.</p>
                </div>
                <div className="rounded-xl border p-4">
                  <p className="text-sm font-medium">2. Create wallet</p>
                  <p className="mt-1 text-xs text-muted-foreground">A unique Circle Arc wallet is created for this agent.</p>
                </div>
                <div className="rounded-xl border p-4">
                  <p className="text-sm font-medium">3. Authorise contract</p>
                  <p className="mt-1 text-xs text-muted-foreground">Veyra authorises the wallet automatically and safely.</p>
                </div>
              </div>
            </div>
          ) : null}

          {step === 4 ? (
            <div className="space-y-6">
              <div className="rounded-xl border p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-lg font-semibold">{form.name}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{form.description}</p>
                  </div>
                  <Badge>{specialisations.find((item) => item.value === form.specialisation)?.label}</Badge>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-base">Capabilities</CardTitle></CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    {[...form.languages, ...form.frameworks, ...form.testing_tools, ...form.task_types].map((item) => (
                      <Badge key={item} variant="outline">{item}</Badge>
                    ))}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-base">Work Policy</CardTitle></CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <p>Budget: {form.minimum_budget_usdc}–{form.maximum_budget_usdc} USDC</p>
                    <p>Concurrent jobs: {form.maximum_active_jobs}</p>
                    <p>Execution limit: {form.maximum_execution_minutes} minutes</p>
                    <p>Repository access: {form.public_repositories_only ? "Public only" : "Public and approved private"}</p>
                  </CardContent>
                </Card>
              </div>

              <div className="rounded-xl border bg-muted/30 p-5">
                <p className="font-medium">What happens next</p>
                <ol className="mt-3 grid gap-2 text-sm text-muted-foreground md:grid-cols-2">
                  <li>1. Test and securely connect the Agent Starter</li>
                  <li>2. Create this agent&apos;s dedicated Circle Arc wallet</li>
                  <li>3. Authorise the wallet on VeyraJobEscrow</li>
                  <li>4. Move the connected agent to qualification</li>
                </ol>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <Button
          type="button"
          variant="outline"
          onClick={() => (step === 0 ? router.push("/dashboard/agents") : setStep((current) => current - 1))}
          disabled={saving}
        >
          <ArrowLeft className="h-4 w-4" /> {step === 0 ? "Cancel" : "Back"}
        </Button>
        {step < steps.length - 1 ? (
          <Button type="button" onClick={next}>
            Continue <ArrowRight className="h-4 w-4" />
          </Button>
        ) : (
          <Button type="button" onClick={() => void createAgent()} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
            {saving ? "Testing and connecting..." : "Test & Connect"}
          </Button>
        )}
      </div>
    </div>
  );
}
