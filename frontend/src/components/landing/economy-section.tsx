import { LandingCtaButton } from "@/components/landing/landing-cta-buttons";
import { ECONOMY } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";
import { cn } from "@/lib/utils";
import { Check } from "lucide-react";


/**
 * Two-column composition. The maintainer card carries a light sand field and
 * ink typography; the agent-owner card stays raised ink with cream typography
 * and anchored lower-edge lighting.
 */
export function EconomySection() {
  return (
    <section className="veyra-section bg-veyra-ink">
      <div className="veyra-container">
        <Reveal>
          <div className="mx-auto max-w-[780px] text-center">
            <h2 className="veyra-h2 mx-auto text-balance text-veyra-cream">{ECONOMY.title}</h2>
            <p className="veyra-lede mx-auto mt-4 text-pretty text-veyra-muted">{ECONOMY.body}</p>
          </div>
        </Reveal>


        <div className="veyra-section-body grid grid-cols-1 gap-8 lg:grid-cols-2">
          {ECONOMY.sides.map((side, index) => {
            const isLight = index === 0;

            return (
              /* Reveal renders the article, so id and anchor behaviour stay
                 exactly where they were in the DOM. */
              <Reveal
                key={side.id}
                as="article"
                variant="panel"
                delay={index * 100}
                className={cn(
                  "veyra-card-pad-lg veyra-anchor relative isolate flex flex-col overflow-hidden rounded-[26px] border lg:min-h-[480px]",
                  isLight
                    ? "border-veyra-ink/[0.14] bg-veyra-sand-light"
                    : "veyra-card-glow border-veyra-cream/[0.14] bg-veyra-ink-raised",
                )}
                id={side.id}
              >

                <h3
                  className={cn(
                    "veyra-card-title-xl relative text-pretty",
                    isLight ? "text-veyra-ink" : "text-veyra-cream",
                  )}
                >
                  {side.title}
                </h3>

                <p
                  className={cn(
                    "veyra-card-body-lg relative mt-3.5 max-w-[38ch]",
                    isLight ? "text-veyra-graphite-light" : "text-veyra-muted",
                  )}
                >
                  {side.body}
                </p>

                <ul className="relative mt-9 space-y-4">
                  {side.points.map((point) => (
                    <li key={point} className="flex items-start gap-3">
                      <Check
                        className={cn(
                          "mt-[3px] h-5 w-5 shrink-0",
                          isLight ? "text-veyra-sand-deep" : "text-veyra-sand",
                        )}
                        aria-hidden="true"
                      />
                      <span
                        className={cn(
                          "text-base leading-6",
                          isLight ? "text-veyra-graphite" : "text-veyra-cream",
                        )}
                      >
                        {point}
                      </span>
                    </li>
                  ))}
                </ul>

                <div className="relative mt-auto pt-10">

                  <LandingCtaButton role={side.role} tone={isLight ? "light" : "dark"}>
                    {side.ctaLabel}
                  </LandingCtaButton>
                </div>
              </Reveal>
            );

          })}
        </div>
      </div>
    </section>
  );
}
