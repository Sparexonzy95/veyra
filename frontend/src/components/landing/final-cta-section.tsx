import { LandingCtaPair } from "@/components/landing/landing-cta-buttons";
import { FINAL_CTA } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";
import { VeyraWordmark } from "@/components/landing/veyra-wordmark";

/**
 * Cinematic panel: large, broad diagonal sand field, text protected by a scrim.
 */
export function FinalCtaSection() {
  return (
    <section className="veyra-section bg-veyra-ink">
      <div className="veyra-container">
        {/* Revealed as one cinematic panel that settles into place rather than
            animating its internal wordmark/headline/CTA separately. */}
        <Reveal variant="panel">
          <div className="relative isolate flex min-h-[440px] w-full flex-col items-center justify-center overflow-hidden rounded-[28px] px-6 py-16 text-center sm:px-12 lg:min-h-[480px] lg:rounded-[32px] lg:px-16">
            <div className="veyra-panel-field" aria-hidden="true" />
            <div className="veyra-panel-scrim" aria-hidden="true" />

            <VeyraWordmark
              uid="cta"
              color="#F5EDE2"
              className="relative z-10 w-[112px] lg:w-[128px]"
            />

            <h2 className="veyra-h2-cta relative z-10 mt-8 text-balance text-veyra-cream">
              {FINAL_CTA.title}
            </h2>
            <p className="veyra-lede relative z-10 mx-auto mt-4 text-pretty text-veyra-muted">
              {FINAL_CTA.body}
            </p>

            <LandingCtaPair tone="dark" className="relative z-10 mt-10 w-full sm:w-auto sm:justify-center" />
          </div>
        </Reveal>
      </div>
    </section>
  );
}
