import { VeyraWordmark } from "@/components/landing/veyra-wordmark";
import Link from "next/link";

/**
 * Compact authenticated footer, shared by the client and agent dashboards.
 *
 * The wordmark is the same `VeyraWordmark` component the landing header and
 * landing footer use, rendering the approved `/brand/veyra-wordmark.jpg`
 * artwork through its knockout filter. It is not a re-drawn text SVG, so the
 * authenticated surface and the marketing site cannot drift apart.
 *
 * Width and padding match the dashboard `main` element so the footer lines up
 * with page content rather than the viewport. Only routes that exist are
 * linked: `/explore` is a real page, so it is the single navigational link
 * here. Documentation, privacy and terms are intentionally absent until those
 * routes exist, because a dead link in an authenticated product is worse than
 * no link.
 */
export function Footer() {
  return (
    <footer className="w-full border-t border-border bg-[var(--veyra-ink)]">
      <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-3 px-4 py-4 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
        <div className="flex items-center gap-2.5">
          <VeyraWordmark
            uid="dashboard-footer"
            color="var(--veyra-cream)"
            className="w-[58px]"
          />
          <span aria-hidden className="text-border">
            |
          </span>
          <p className="text-xs text-[var(--veyra-muted)]">
            Autonomous work. Verified outcomes.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/explore"
            className="text-xs text-[var(--veyra-muted)] transition-colors hover:text-[var(--veyra-cream)]"
          >
            Explore Issues
          </Link>
          <span className="rounded-full border border-border px-2 py-0.5 text-xs text-[var(--veyra-muted)]">
            Arc Testnet
          </span>
        </div>
      </div>
    </footer>
  );
}
