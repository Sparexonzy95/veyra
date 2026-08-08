"use client";

import { ArrowRight, Bot, BriefcaseBusiness, Check, Loader2 } from "lucide-react";

/**
 * The single Veyra actor choice.
 *
 * Onboarding, the post-login chooser and later mode switching all render this
 * one component. Previously the signup dialog and `/workspace` maintained two
 * separate designs of the same decision, which drifted apart every time either
 * side changed. There is now one design and one source of truth.
 *
 * Capabilities are additive, never exclusive: an account may hold both, so the
 * cards report what already exists rather than locking the other side out.
 */

type VeyraChoiceProps = {
  busy?: boolean;
  onChooseMaintainer: () => void;
  onChooseAgentOwner: () => void;
  hasMaintainer?: boolean;
  hasAgentOwner?: boolean;
  /** Tighter padding for dialog use. The design is otherwise identical. */
  compact?: boolean;
};

const CHOICES = [
  {
    key: "maintainer",
    title: "For Maintainers",
    description: "Publish verified GitHub tasks and fund work securely in USDC.",
    cta: "Publish Tasks",
    icon: BriefcaseBusiness,
    primary: true,
  },
  {
    key: "agent-owner",
    title: "For Agent Owners",
    description: "Connect autonomous agents to complete verified software work.",
    cta: "Run Agents",
    icon: Bot,
    primary: false,
  },
] as const;

export function VeyraChoice({
  busy = false,
  onChooseMaintainer,
  onChooseAgentOwner,
  hasMaintainer = false,
  hasAgentOwner = false,
  compact = false,
}: VeyraChoiceProps) {
  return (
    <div className={`grid items-stretch gap-4 sm:grid-cols-2 ${compact ? "" : "sm:gap-5"}`}>
      {CHOICES.map((choice) => {
        const Icon = choice.icon;
        const isMaintainer = choice.key === "maintainer";
        const action = isMaintainer ? onChooseMaintainer : onChooseAgentOwner;
        const active = isMaintainer ? hasMaintainer : hasAgentOwner;

        return (
          <article
            key={choice.key}
            className={`group relative flex h-full flex-col overflow-hidden rounded-[18px] border border-veyra-cream/[0.12] bg-veyra-graphite/40 transition-[border-color,box-shadow] duration-300 hover:border-veyra-sand/35 hover:shadow-[0_18px_50px_rgba(0,0,0,0.28)] motion-reduce:transition-none ${
              compact ? "p-5" : "p-5 sm:p-6"
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-veyra-sand/20 bg-veyra-sand/[0.08] text-veyra-sand">
                <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
              </span>
              {active ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-veyra-sand/25 bg-veyra-sand/10 px-2.5 py-1 text-[11px] font-medium text-veyra-sand">
                  <Check className="h-3 w-3" aria-hidden="true" />
                  Active
                </span>
              ) : null}
            </div>

            <div className="mt-5 flex-1">
              <h2 className="text-lg font-semibold tracking-[-0.02em] text-veyra-cream sm:text-xl">
                {choice.title}
              </h2>
              <p className="mt-2 max-w-[34ch] text-sm leading-6 text-veyra-muted">
                {choice.description}
              </p>
            </div>

            <button
              type="button"
              disabled={busy}
              onClick={action}
              className={`group/button mt-6 inline-flex h-11 w-full items-center justify-between rounded-full border px-5 text-sm font-semibold transition-[background-color,border-color,color] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink disabled:pointer-events-none disabled:opacity-60 motion-reduce:transition-none ${
                choice.primary
                  ? "border-veyra-cream bg-veyra-cream text-veyra-ink hover:border-veyra-sand hover:bg-veyra-sand"
                  : "border-veyra-cream/20 bg-transparent text-veyra-cream hover:border-veyra-sand/60 hover:text-veyra-sand"
              }`}
            >
              <span>{busy ? "Preparing…" : active ? "Continue" : choice.cta}</span>
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <ArrowRight
                  className="h-4 w-4 shrink-0 transition-transform group-hover/button:translate-x-1 motion-reduce:transform-none"
                  aria-hidden="true"
                />
              )}
            </button>
          </article>
        );
      })}
    </div>
  );
}
