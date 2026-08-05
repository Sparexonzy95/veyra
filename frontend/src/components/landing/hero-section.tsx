import { LandingCtaPair } from "@/components/landing/landing-cta-buttons";
import { HERO } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";


/**
 * Hero with animated sand wave.
 *
 * The wave is anchored to the lower edge, animated with CSS only, and uses
 * transform + opacity so the animation remains smooth. The text and CTAs sit
 * in the stable dark area above the brightest highlight.
 *
 * The hero is content-driven, with a minimum floor rather than a fixed height,
 * so it adapts to shorter viewports without clipping.
 */
export function HeroSection() {
  return (
    <section
      id="top"
      className="veyra-anchor relative isolate bg-veyra-ink"
      style={{ backgroundColor: "#050505" }}
    >
      {/* Animated wave field: three layered gradients that drift slowly. */}
      <div className="veyra-wave-field" aria-hidden="true">
        <div className="veyra-wave-layer veyra-hero-wave-a" />
        <div className="veyra-wave-layer veyra-hero-wave-b" />
        <div className="veyra-wave-layer veyra-hero-wave-glow" />
      </div>

      <div className="veyra-container veyra-hero-pad relative z-10 flex flex-col items-center text-center">
        <Reveal delay={80}>
          <h1 className="veyra-h1 text-balance text-veyra-cream">
            {HERO.headline.map((line, index) => (
              <span key={index} className="block">
                {line}
              </span>
            ))}
          </h1>
        </Reveal>

        <Reveal delay={160}>
          <p className="veyra-hero-lede mx-auto mt-6 text-pretty text-veyra-muted">{HERO.body}</p>
        </Reveal>

        <Reveal delay={240}>
          <LandingCtaPair tone="dark" className="mt-9 w-full sm:w-auto sm:justify-center" />
        </Reveal>

        <Reveal delay={320}>
          <p className="mt-9 max-w-[46ch] text-sm leading-relaxed text-veyra-muted-dark sm:max-w-none">
            {HERO.trustLine}
          </p>
        </Reveal>
      </div>

    </section>
  );
}
