"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { VeyraMark } from "@/components/auth/veyra-mark";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { AlertTriangle, Check, Loader2 } from "lucide-react";

/**
 * Wallet preparation.
 *
 * One status at a time and one spinner, by design. Circle tokens, challenge
 * IDs and retry counters are deliberately absent: they are operational detail
 * the person approving the wallet cannot act on, and showing them turns a
 * two-line reassurance into a support ticket.
 */

const STATES = {
  preparing: {
    title: "Preparing your Arc wallet",
    text: "Setting up your secure Veyra wallet.",
    note: "Preparing securely",
  },
  approval: {
    title: "Approve wallet setup",
    text: "Confirm the request in the Circle window.",
    note: "Waiting for approval",
  },
  ready: {
    title: "Wallet ready",
    text: "Your Arc wallet is connected.",
    note: "",
  },
  error: {
    title: "Wallet setup failed",
    text: "We could not complete wallet setup. Try again.",
    note: "",
  },
} as const;

const primaryButton =
  "inline-flex h-11 items-center justify-center rounded-full bg-veyra-cream px-5 text-sm font-semibold text-veyra-ink transition-colors hover:bg-veyra-sand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-graphite motion-reduce:transition-none";

const secondaryButton =
  "inline-flex h-11 items-center justify-center rounded-full border border-veyra-cream/15 px-5 text-sm font-semibold text-veyra-cream transition-colors hover:border-veyra-sand/50 hover:text-veyra-sand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-graphite motion-reduce:transition-none";

export function WalletSetupDialog() {
  const {
    walletSetupOpen,
    walletSetupPhase,
    continueWalletSetup,
    retryWalletSetup,
    cancelWalletSetup,
  } = useVeyra();

  const content = STATES[walletSetupPhase];
  const pending = walletSetupPhase === "preparing" || walletSetupPhase === "approval";
  const failed = walletSetupPhase === "error";

  return (
    <Dialog open={walletSetupOpen}>
      <DialogContent
        className="veyra-scope overflow-hidden rounded-[22px] border-veyra-cream/[0.12] bg-veyra-graphite p-0 text-veyra-cream shadow-[0_26px_100px_rgba(0,0,0,0.6)] sm:max-w-[420px]"
        hideCloseButton
      >
        <div className="relative p-7">
          {/* Restrained: a single low-alpha wash, not a lit panel. */}
          <div
            className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-[radial-gradient(ellipse_at_top,rgba(196,173,141,0.10),transparent_72%)]"
            aria-hidden="true"
          />

          <div className="relative">
            <span
              className={`flex h-12 w-12 items-center justify-center rounded-2xl border ${
                failed
                  ? "border-red-400/25 bg-red-400/10 text-red-300"
                  : "border-veyra-sand/25 bg-veyra-sand/[0.08] text-veyra-sand"
              }`}
            >
              {failed ? (
                <AlertTriangle className="h-5 w-5" aria-hidden="true" />
              ) : walletSetupPhase === "ready" ? (
                <Check className="h-5 w-5" aria-hidden="true" />
              ) : (
                <VeyraMark uid="wallet-setup" color="var(--veyra-sand)" className="h-6 w-6" title="Veyra" />
              )}
            </span>

            <DialogTitle className="mt-6 text-[1.375rem] font-semibold tracking-[-0.025em] text-veyra-cream">
              {content.title}
            </DialogTitle>
            <DialogDescription className="mt-2 text-sm leading-6 text-veyra-muted">
              {content.text}
            </DialogDescription>

            {pending ? (
              <div
                className="mt-7 flex items-center gap-3 border-t border-veyra-cream/[0.09] pt-5 text-sm text-veyra-muted-dark"
                role="status"
                aria-live="polite"
              >
                <Loader2
                  className="h-4 w-4 animate-spin text-veyra-sand motion-reduce:animate-none"
                  aria-hidden="true"
                />
                <span>{content.note}</span>
              </div>
            ) : null}

            {walletSetupPhase === "ready" ? (
              <button type="button" onClick={continueWalletSetup} className={`${primaryButton} mt-7 w-full`}>
                Continue
              </button>
            ) : null}

            {failed ? (
              <div className="mt-7 grid gap-3 sm:grid-cols-2">
                <button type="button" onClick={() => void retryWalletSetup()} className={primaryButton}>
                  Try Again
                </button>
                <button type="button" onClick={cancelWalletSetup} className={secondaryButton}>
                  Cancel
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
