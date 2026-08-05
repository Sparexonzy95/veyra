import { EconomySection } from "@/components/landing/economy-section";
import { FaqSection } from "@/components/landing/faq-section";
import { FinalCtaSection } from "@/components/landing/final-cta-section";
import { HeroSection } from "@/components/landing/hero-section";
import { HowItWorksSection } from "@/components/landing/how-it-works-section";
import { LandingFooter } from "@/components/landing/landing-footer";
import { LandingHeader } from "@/components/landing/landing-header";
import { ProblemSection } from "@/components/landing/problem-section";
import { LandingMotionRoot } from "@/components/landing/section-reveal";
import { TrustSection } from "@/components/landing/trust-section";
import { TrustStrip } from "@/components/landing/trust-strip";


/**
 * Landing page.
 *
 * `veyra-landing` is the single root that owns the landing font stack and the
 * horizontal clip. Every landing component inherits its typeface from here;
 * the dashboard and application surfaces are untouched.
 *
 * Each idea is explained once. The canvas stays ink throughout; separation
 * comes from spacing, borders and contained lighting rather than from
 * alternating background slabs. Sand appears only as anchored light fields.
 */
export default function Home() {
  return (
    <LandingMotionRoot className="veyra-landing relative min-h-screen bg-veyra-ink">
      <a href="#main" className="veyra-skip-link">
        Skip to content
      </a>

      <LandingHeader />
      <main id="main">
        <HeroSection />
        <TrustStrip />
        <ProblemSection />
        <HowItWorksSection />
        <EconomySection />
        <TrustSection />
        <FaqSection />
        <FinalCtaSection />
      </main>
      <LandingFooter />
    </LandingMotionRoot>
  );
}


