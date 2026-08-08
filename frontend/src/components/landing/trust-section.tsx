import {
  TRUST_INFRASTRUCTURE,
  WHY_ARC,
} from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";
import {
  Award,
  CircleDollarSign,
  GitPullRequest,
  ShieldCheck,
  Wallet,
  Zap,
} from "lucide-react";

const ICONS = {
  git: GitPullRequest,
  shield: ShieldCheck,
  wallet: Wallet,
  karma: Award,
} as const;

const ARC_ICONS = {
  money: CircleDollarSign,
  settlement: ShieldCheck,
  speed: Zap,
} as const;

/** Four-column grid. Consistent card height, one sentence each. */
export function TrustSection() {
  return (
    <section id="trust" className="veyra-section veyra-anchor bg-veyra-ink">
      <div className="veyra-container">
        <Reveal>
          <div className="mx-auto max-w-[780px] text-center">
            <h2 className="veyra-h2 mx-auto text-balance text-veyra-cream">
              {TRUST_INFRASTRUCTURE.title}
            </h2>
            <p className="veyra-lede mx-auto mt-4 text-pretty text-veyra-muted">
              {TRUST_INFRASTRUCTURE.body}
            </p>
          </div>
        </Reveal>

        <ul className="veyra-section-body grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {TRUST_INFRASTRUCTURE.items.map((item, index) => {
            const Icon = ICONS[item.icon];
            return (
              /* Small stagger only. Four cards animating in sequence at a
                 longer interval would read as a list being dealt out. */
              <Reveal
                key={item.title}
                as="li"
                delay={index * 75}
                className="veyra-trust-card flex h-full flex-col rounded-[22px] border border-veyra-cream/[0.14] bg-veyra-ink-raised lg:min-h-[220px]"
              >
                <Icon className="h-6 w-6 text-veyra-sand" aria-hidden="true" />
                <h3 className="veyra-card-title-sm mt-6 text-veyra-cream">{item.title}</h3>
                {/* 15px / 1.6, a step up from the shared card body, because
                    four narrow columns are the hardest place to read. */}
                <p className="veyra-trust-body mt-3 max-w-[34ch] text-veyra-muted">{item.body}</p>
              </Reveal>
            );
          })}
        </ul>

        <Reveal delay={120}>
          <p className="mt-10 text-center text-[0.9375rem] text-veyra-muted-dark">
            {TRUST_INFRASTRUCTURE.footnote}
          </p>
        </Reveal>

        <div className="mt-20 border-t border-veyra-cream/[0.14] pt-16 lg:mt-24 lg:grid lg:grid-cols-[0.9fr_1.6fr] lg:gap-16 lg:pt-20">
          <Reveal>
            <div>
              <p className="text-sm font-semibold uppercase tracking-wide text-veyra-sand">
                Arc settlement layer
              </p>
              <h2 className="veyra-h2 mt-3 text-balance text-veyra-cream">
                {WHY_ARC.title}
              </h2>
              <p className="veyra-lede mt-4 text-pretty text-veyra-muted">
                {WHY_ARC.body}
              </p>
            </div>
          </Reveal>

          <ul className="mt-10 grid gap-8 sm:grid-cols-3 lg:mt-0">
            {WHY_ARC.points.map((point, index) => {
              const Icon = ARC_ICONS[point.icon];
              return (
                <Reveal key={point.title} as="li" delay={index * 75}>
                  <Icon className="h-6 w-6 text-veyra-sand" aria-hidden="true" />
                  <h3 className="veyra-card-title-sm mt-5 text-veyra-cream">
                    {point.title}
                  </h3>
                  <p className="veyra-trust-body mt-3 text-veyra-muted">
                    {point.body}
                  </p>
                </Reveal>
              );
            })}
          </ul>
        </div>
      </div>
    </section>
  );
}
