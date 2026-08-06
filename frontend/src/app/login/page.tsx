"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { VeyraMark } from "@/components/auth/veyra-mark";
import { AlertCircle, GitBranch, Landmark, Loader2, ShieldCheck } from "lucide-react";
import { FcGoogle } from "react-icons/fc";
import { useId } from "react";
import Link from "next/link";

/**
 * Product context, not controls. These are presentational only: no handlers,
 * no hover affordance, no tab stop.
 */
const VALUE_TILES = [
  { icon: GitBranch, label: "GitHub-native" },
  { icon: ShieldCheck, label: "Independently verified" },
  { icon: Landmark, label: "Settled on Arc" },
] as const;

export default function LoginPage() {
  const {
    sdkReady,
    busy,
    authPhase,
    status,
    error,
    me,
    loginWithGoogle,
  } = useVeyra();

  const errorId = useId();

  const locked = !sdkReady || busy;
  const processing = authPhase !== "idle" && authPhase !== "error";

  if (processing || (me?.authenticated && !error)) {
    return (
      <main className="veyra-auth">
        <div className="veyra-auth-field" aria-hidden="true" />
        <div className="veyra-auth-center">
          <div className="flex flex-col items-center gap-3" role="status" aria-live="polite">
            <Loader2 className="h-6 w-6 animate-spin text-veyra-sand" aria-hidden="true" />
            <p className="text-sm text-veyra-muted">
              {status ?? "Preparing secure sign-in…"}
            </p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="veyra-auth">
      <div className="veyra-auth-field" aria-hidden="true" />

      <div className="veyra-auth-center">
        <section className="veyra-auth-card veyra-auth-enter">
          <div className="veyra-auth-mark-wrap">
            <span className="veyra-auth-mark-halo" aria-hidden="true" />
            <VeyraMark
              uid="login"
              color="var(--veyra-cream)"
              className="veyra-auth-mark"
              title="Veyra"
            />
          </div>

          <h1 className="veyra-auth-title">Welcome to Veyra</h1>
          <p className="veyra-auth-lede">
            Access autonomous GitHub work, independent verification, and programmable
            USDC settlement.
          </p>

          <ul className="veyra-auth-tiles">
            {VALUE_TILES.map(({ icon: Icon, label }) => (
              <li key={label} className="veyra-auth-tile">
                <Icon className="veyra-auth-tile-icon" aria-hidden="true" />
                <span className="veyra-auth-tile-label">{label}</span>
              </li>
            ))}
          </ul>

          <div className="veyra-auth-body">
            <button
              type="button"
              onClick={() => void loginWithGoogle()}
              disabled={locked}
              aria-describedby={error ? errorId : undefined}
              className="veyra-auth-google"
            >
              <FcGoogle className="h-5 w-5 shrink-0" aria-hidden="true" />
              <span>Continue with Google</span>
            </button>
          </div>

          {error ? (
            <p id={errorId} className="veyra-auth-error" role="alert">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </p>
          ) : null}

          <p className="veyra-auth-helper">
            Your Google account securely connects you to your Veyra profile and Circle wallet.
          </p>
        </section>

        <Link href="/" className="veyra-auth-back">
          Back to Veyra
        </Link>
      </div>
    </main>
  );
}
