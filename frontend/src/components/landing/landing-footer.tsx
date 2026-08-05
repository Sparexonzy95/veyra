import { FOOTER, FOOTER_SOCIALS } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";
import { VeyraWordmark } from "@/components/landing/veyra-wordmark";
import { cn } from "@/lib/utils";
import { Github, Linkedin, MessageCircle, Send, Twitter } from "lucide-react";

/** Icons come from lucide-react, already a project dependency. */
const SOCIAL_ICONS = {
  github: Github,
  x: Twitter,
  discord: MessageCircle,
  telegram: Send,
  linkedin: Linkedin,
} as const;

const BADGE_BASE = "inline-flex h-11 w-11 items-center justify-center rounded-full border";

/**
 * Footer social row.
 *
 * Only a platform with a real, already-known Veyra URL becomes an anchor.
 * Everything else renders as a non-interactive badge: no `href="#"`, not
 * focusable, and its accessible label states the platform is not live yet.
 *
 * The two states are deliberately separated *before* any interaction, so the
 * live platform is identifiable at a glance rather than only on hover:
 * full-strength cream on a brighter border and a lifted surface, against
 * 40% opacity on a dim border.
 */
function SocialRow({ className }: { className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-3", className)}>
      {FOOTER_SOCIALS.map((social) => {
        const Icon = SOCIAL_ICONS[social.icon];

        if (social.href) {
          return (
            <li key={social.id}>
              <a
                href={social.href}
                target="_blank"
                rel="noopener noreferrer"
                title={social.label}
                aria-label={social.label}
                className={cn(
                  BADGE_BASE,
                  "group cursor-pointer border-veyra-cream/30 bg-veyra-cream/[0.10] text-veyra-cream",
                  "opacity-100 transition-colors duration-200",
                  "hover:border-veyra-cream/55 hover:bg-veyra-sand/20 hover:text-veyra-cream-bright",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink",
                  "motion-reduce:transition-none",
                )}
              >
                <Icon
                  className="h-[18px] w-[18px] transition-transform duration-200 group-hover:-translate-y-[2px] motion-reduce:transition-none motion-reduce:group-hover:translate-y-0"
                  aria-hidden="true"
                />
              </a>
            </li>
          );
        }

        return (
          <li key={social.id}>
            {/* Disabled: communicates state without pretending to be a link.
                No anchor, no href, no tabindex, no hover movement. */}
            <span
              role="img"
              aria-label={social.label}
              aria-disabled="true"
              title={social.label}
              className={cn(
                BADGE_BASE,
                "cursor-default border-veyra-cream/[0.08] bg-veyra-cream/[0.03] text-veyra-muted-dark opacity-40",
              )}
            >
              <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Footer with an independently animated sand wave anchored to the bottom edge.
 * All content sits on a stable dark layer above the wave, and the generous
 * bottom padding keeps the copyright clear of the brightest highlight.
 */
export function LandingFooter() {
  const year = new Date().getFullYear();

  return (
    <footer
      className="relative isolate overflow-hidden bg-veyra-ink pb-[150px] pt-[72px] md:pb-[165px] md:pt-[88px] lg:pb-[180px] lg:pt-[104px]"
      style={{ backgroundColor: "#050505" }}
    >
      {/* Independent of the section-reveal system: the wave starts moving as
          soon as the footer is painted and never waits on an observer. */}
      <div className="veyra-wave-field" aria-hidden="true">
        <div className="veyra-wave-layer veyra-footer-wave-a" />
        <div className="veyra-wave-layer veyra-footer-wave-b" />
        <div className="veyra-wave-layer veyra-footer-wave-glow" />
      </div>

      {/* The whole content layer fades in as one unit. Animating each footer
          link separately would be noise at the very end of the page. */}
      <Reveal variant="tight" className="veyra-container relative z-10">
        <div className="flex flex-col gap-12 lg:flex-row lg:justify-between lg:gap-16">
          <div className="max-w-[380px]">
            <VeyraWordmark uid="footer" color="#F5EDE2" className="w-[120px] lg:w-[132px]" />
            {/* Description lifted from muted to a brighter secondary tone. */}
            <p className="mt-5 text-[0.9375rem] leading-[1.6] text-veyra-muted sm:text-base">
              {FOOTER.description}
            </p>
          </div>

          <nav aria-label="Footer" className="grid grid-cols-2 gap-10 sm:flex sm:gap-16">
            {FOOTER.columns.map((column) => (
              <div key={column.heading}>
                {/* Headings are the brightest thing in the footer nav so the
                    grouping stays legible against the wave. */}
                <h2 className="veyra-footer-label text-veyra-muted">{column.heading}</h2>
                <ul className="mt-5 space-y-1">
                  {column.links.map((link) => (
                    <li key={link.href}>
                      <a
                        href={link.href}
                        className="inline-flex min-h-[44px] items-center text-[0.9375rem] text-veyra-muted transition-colors duration-200 hover:text-veyra-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink motion-reduce:transition-none"
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>

        {/* Mobile and tablet: socials sit below the navigation, above the
            divider. Desktop: they move onto the copyright row. */}
        <SocialRow className="mt-12 lg:hidden" />

        <div className="mt-10 flex flex-col gap-6 border-t border-veyra-cream/[0.12] pt-8 sm:mt-12 lg:flex-row lg:items-center lg:justify-between">
          {/* Copyright stays tertiary, but is lifted off the near-invisible
              muted-dark it used before. */}
          <p className="text-sm text-veyra-muted-dark">© {year} Veyra</p>
          <SocialRow className="hidden lg:flex" />
        </div>
      </Reveal>
    </footer>
  );
}
