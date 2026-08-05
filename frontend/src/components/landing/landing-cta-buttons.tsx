"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { cn } from "@/lib/utils";
import { ArrowRight, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

type Role = "client" | "agent-owner";
type Variant = "primary" | "secondary";
type Tone = "light" | "dark";

/**
 * Landing CTAs reuse the existing authentication and role-selection behaviour.
 *
 * Signed out -> /login (the Circle sign-in surface).
 * Signed in without the capability -> /workspace, where the existing
 * chooseClientRole / chooseAgentOwnerRole wallet flow already lives.
 * Signed in with the capability -> straight into that workspace.
 *
 * No new routes and no duplicated wallet logic are introduced here.
 */
function useRoleDestination() {
  const { me } = useVeyra();

  return (role: Role) => {
    if (!me?.authenticated) return "/login";
    const capability = role === "client" ? "CLIENT" : "AGENT_OWNER";
    if (me.capabilities?.includes(capability)) {
      return role === "client" ? "/client" : "/agent-owner";
    }
    return "/workspace";
  };
}

const SURFACES: Record<Tone, Record<Variant, string>> = {
  /* "light" = sitting on a sand or cream surface, so the button is ink. */
  light: {
    primary:
      "border border-veyra-ink bg-veyra-ink text-veyra-cream hover:bg-veyra-graphite focus-visible:ring-veyra-ink",
    secondary:
      "border border-veyra-ink/30 bg-transparent text-veyra-ink hover:bg-veyra-ink/[0.06] focus-visible:ring-veyra-ink",
  },
  /* "dark" = sitting on ink, so the button is cream. */
  dark: {
    primary:
      "border border-veyra-cream bg-veyra-cream text-veyra-ink hover:bg-veyra-cream-bright focus-visible:ring-veyra-cream",
    secondary:
      "border border-veyra-cream/30 bg-transparent text-veyra-cream hover:border-veyra-cream/60 hover:bg-veyra-cream/10 focus-visible:ring-veyra-cream",
  },
};


export function LandingCtaButton({
  role,
  variant = "primary",
  tone = "light",
  size = "default",
  className,
  children,
}: {
  role: Role;
  variant?: Variant;
  tone?: Tone;
  size?: "default" | "sm";
  className?: string;
  children: React.ReactNode;
}) {
  const { sdkReady } = useVeyra();
  const destination = useRoleDestination();
  const router = useRouter();

  return (
    <button
      type="button"
      onClick={() => router.push(destination(role))}
      disabled={!sdkReady}
      className={cn(
        "group inline-flex items-center justify-center gap-2 rounded-full font-semibold tracking-tight",
        size === "sm" ? "min-h-[44px] px-5 text-sm" : "min-h-[48px] px-7 text-[0.9375rem]",

        "transition-[background-color,color,border-color] duration-200 motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
        tone === "dark" ? "focus-visible:ring-offset-veyra-ink" : "focus-visible:ring-offset-transparent",

        "disabled:pointer-events-none disabled:opacity-60",
        SURFACES[tone][variant],
        className,
      )}
    >
      {children}
      {sdkReady ? (
        <ArrowRight
          className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1 motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
          aria-hidden="true"
        />
      ) : (
        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      )}
    </button>
  );
}

export function LandingCtaPair({ className, tone = "light" }: { className?: string; tone?: Tone }) {
  return (
    <div className={cn("flex flex-col gap-3 sm:flex-row sm:flex-wrap", className)}>
      <LandingCtaButton role="client" tone={tone}>
        Hire an Agent
      </LandingCtaButton>
      <LandingCtaButton role="agent-owner" variant="secondary" tone={tone}>
        Run an Agent
      </LandingCtaButton>
    </div>
  );
}
