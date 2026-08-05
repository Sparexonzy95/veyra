import { PROBLEM } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";


/**
 * Restrained line illustrations. Each is a plain SVG built from Veyra strokes
 * so the panels stay technical rather than decorative.
 */
function PanelArt({ art }: { art: "queue" | "inspect" | "escrow" }) {
  const stroke = "rgba(245, 237, 226, 0.55)";
  const accent = "#C4AD8D";

  if (art === "queue") {
    return (
      <svg viewBox="0 0 160 160" fill="none" className="h-full w-full" aria-hidden="true">
        {/* A queue of tasks where only the first is moving. */}
        {[0, 1, 2, 3].map((i) => (
          <rect
            key={i}
            x="34"
            y={30 + i * 26}
            width="92"
            height="16"
            rx="8"
            stroke={i === 0 ? accent : stroke}
            strokeOpacity={i === 0 ? 1 : 0.5 - i * 0.12}
            strokeWidth="1.25"
          />
        ))}
        <circle cx="80" cy="38" r="3" fill={accent} />
      </svg>
    );
  }

  if (art === "inspect") {
    return (
      <svg viewBox="0 0 160 160" fill="none" className="h-full w-full" aria-hidden="true">
        {/* Code lines under a lens: output that still needs checking. */}
        {[0, 1, 2, 3, 4].map((i) => (
          <line
            key={i}
            x1="36"
            y1={44 + i * 18}
            x2={i % 2 === 0 ? 118 : 96}
            y2={44 + i * 18}
            stroke={stroke}
            strokeOpacity={0.45}
            strokeWidth="1.25"
            strokeLinecap="round"
          />
        ))}
        <circle cx="98" cy="98" r="24" stroke={accent} strokeWidth="1.5" />
        <line x1="115" y1="115" x2="130" y2="130" stroke={accent} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 160 160" fill="none" className="h-full w-full" aria-hidden="true">
      {/* Value held on one side, proof missing on the other. */}
      <circle cx="52" cy="80" r="22" stroke={accent} strokeWidth="1.5" />
      <path d="M52 70v20M46 76h12M46 84h12" stroke={accent} strokeWidth="1.25" strokeLinecap="round" />
      <circle cx="112" cy="80" r="22" stroke={stroke} strokeOpacity="0.45" strokeWidth="1.5" strokeDasharray="4 5" />
      <path
        d="M78 80h8m6 0h8"
        stroke={stroke}
        strokeOpacity="0.5"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ProblemSection() {
  return (
    <section id="problem" className="veyra-section veyra-anchor bg-veyra-ink">
      <div className="veyra-container">
        <Reveal>
          <div className="mx-auto max-w-[780px] text-center">
            <h2 className="veyra-h2 mx-auto text-balance text-veyra-cream">{PROBLEM.title}</h2>
            <p className="veyra-lede mx-auto mt-4 text-pretty text-veyra-muted">{PROBLEM.body}</p>
          </div>
        </Reveal>


        {/* Two columns on tablet; the third card centres itself on the last
            row rather than stretching across the full width. */}
        <ul className="veyra-section-body grid grid-cols-1 gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-3">
          {PROBLEM.cards.map((card, index) => (
            /* Reveal renders the li itself, so the stagger lands on the grid
               item rather than on a wrapper inside it. */
            <Reveal
              key={card.title}
              as="li"
              delay={index * 90}
              className={
                index === 2
                  ? "sm:col-span-2 sm:mx-auto sm:w-[calc(50%-1rem)] lg:col-span-1 lg:mx-0 lg:w-auto"
                  : undefined
              }
            >
              {/* Square visual panel. Text lives beneath it, not inside. */}
              <div className="relative isolate aspect-square w-full overflow-hidden rounded-[22px] border border-veyra-cream/[0.14] bg-veyra-ink-raised sm:min-h-[300px] lg:min-h-[330px]">
                <div
                  className="veyra-panel-glow absolute inset-x-0 bottom-0 h-1/2 opacity-[0.22]"
                  aria-hidden="true"
                />
                {/* Tighter padding = a materially larger illustration. */}
                <div className="relative flex h-full items-center justify-center p-6 sm:p-7">
                  <PanelArt art={card.art} />
                </div>
              </div>

              <h3 className="veyra-card-title-lg mt-6 text-pretty text-veyra-cream">
                {card.title}
              </h3>
              <p className="veyra-card-body-lg mt-2.5 max-w-[42ch] text-veyra-muted">
                {card.body}
              </p>
            </Reveal>
          ))}
        </ul>

      </div>
    </section>

  );
}
