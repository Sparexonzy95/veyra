import { HOW_IT_WORKS } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";
import { cn } from "@/lib/utils";
import { CheckCircle2, Coins, FileCode2, Workflow } from "lucide-react";


const ICONS = {
  define: FileCode2,
  build: Workflow,
  verify: CheckCircle2,
  settle: Coins,
} as const;

/**
 * Vertical timeline.
 *
 * Desktop: the rail runs down the centre and cards alternate either side.
 * Mobile: the rail moves to the left, every card aligns right of it, and the
 * step marker sits on the rail. The rail is inset from the first and last
 * marker centres so it does not overshoot past the end circles.
 */
export function HowItWorksSection() {
  return (
    <section id="how-it-works" className="veyra-section veyra-anchor bg-veyra-ink">

      <div className="veyra-container">
        <Reveal>
          <div className="mx-auto max-w-[780px] text-center">
            <h2 className="veyra-h2 mx-auto text-balance text-veyra-cream">{HOW_IT_WORKS.title}</h2>
            <p className="veyra-lede mx-auto mt-4 text-pretty text-veyra-muted">
              {HOW_IT_WORKS.body}
            </p>
          </div>
        </Reveal>

        <ol className="veyra-section-body relative">
          {/* Rail. top/bottom inset by ~22px keeps it between the marker centres.
              It settles in just before the first card, using a restrained
              scaleY rather than a long line-drawing effect. */}
          <Reveal
            variant="rail"
            delay={120}
            className="absolute bottom-[22px] left-[22px] top-[22px] w-px bg-veyra-sand-deep/40 lg:left-1/2"
          >
            <span className="sr-only" />
          </Reveal>

          {HOW_IT_WORKS.steps.map((step, index) => {
            const Icon = ICONS[step.icon];
            const onLeft = index % 2 === 0;

            return (
              <li
                key={step.number}
                className={cn("relative pl-16 lg:pl-0", index > 0 && "mt-10 lg:mt-14")}
              >
                {/* Marker sits on the rail at both breakpoints. */}
                <span
                  className="absolute left-0 top-0 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-veyra-sand text-[0.9375rem] font-bold text-veyra-ink shadow-[0_0_0_6px_rgba(5,5,5,1),0_0_26px_rgba(196,173,141,0.35)] lg:left-1/2 lg:h-[46px] lg:w-[46px] lg:-translate-x-1/2"
                  aria-hidden="true"
                >
                  {step.number}
                </span>

                {/* Narrower gutter pulls the cards closer to the rail. */}
                <div className="lg:grid lg:grid-cols-2 lg:gap-x-10 xl:gap-x-12">
                  {/* Cards enter from their own side of the rail on desktop.
                      Below lg the stylesheet flattens both directions to a
                      simple rise, matching the single-sided mobile layout.
                      The stagger is capped at index 3 so the sequence stays
                      quick rather than accumulating a long delay. */}
                  <Reveal
                    variant={onLeft ? "left" : "right"}
                    delay={200 + index * 120}
                    className={cn(
                      "veyra-card-glow veyra-timeline-card relative isolate overflow-hidden rounded-[24px] border border-veyra-cream/[0.14] bg-veyra-ink-raised lg:max-w-[560px] xl:max-w-[580px]",
                      onLeft ? "lg:col-start-1 lg:ml-auto" : "lg:col-start-2",
                    )}
                  >
                    <Icon className="relative h-[22px] w-[22px] text-veyra-sand" aria-hidden="true" />
                    <h3 className="veyra-card-title-lg relative mt-5 text-veyra-cream">
                      {step.title}
                    </h3>
                    <p className="veyra-card-body-lg relative mt-2.5 max-w-[46ch] text-veyra-muted">
                      {step.body}
                    </p>
                  </Reveal>
                </div>
              </li>
            );
          })}
        </ol>

      </div>
    </section>
  );
}
