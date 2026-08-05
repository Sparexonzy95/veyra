import { TRUST_STRIP } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";
import { GitPullRequest, Landmark, ShieldCheck, Wallet } from "lucide-react";


const ICONS = {
  git: GitPullRequest,
  shield: ShieldCheck,
  wallet: Wallet,
  arc: Landmark,
} as const;

/** Compact proof line. Labels only, no descriptions. */
export function TrustStrip() {
  return (
    <section aria-label="What Veyra is built on" className="bg-veyra-ink">
      <div className="veyra-container">
        {/* Revealed as one unit: four separate item animations would turn a
            supporting proof line into an event. */}
        <Reveal variant="tight">
          <ul className="grid grid-cols-2 border-y border-veyra-cream/10 lg:grid-cols-4">
            {TRUST_STRIP.map(({ label, icon }) => {
              const Icon = ICONS[icon];
              return (
                <li
                  key={label}
                  className="flex min-h-[56px] items-center justify-center gap-2.5 px-3 py-3 text-center lg:min-h-[72px]"
                >
                  <Icon
                    className="h-[21px] w-[21px] shrink-0 text-veyra-sand"
                    aria-hidden="true"
                  />
                  <span className="text-sm font-medium tracking-tight text-veyra-muted sm:text-[0.9375rem]">
                    {label}
                  </span>
                </li>
              );
            })}
          </ul>
        </Reveal>
      </div>

    </section>
  );
}
