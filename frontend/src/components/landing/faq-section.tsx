"use client";

import { FAQ } from "@/components/landing/landing-content";
import { Reveal } from "@/components/landing/section-reveal";
import { Plus, X } from "lucide-react";
import { useState } from "react";

/** Single centred accordion on a raised ink surface. */
export function FaqSection() {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="faq" className="veyra-section veyra-anchor bg-veyra-ink">
      <div className="veyra-container">
        <Reveal>
          <div className="mx-auto max-w-[780px] text-center">
            <h2 className="veyra-h2 mx-auto text-balance text-veyra-cream">{FAQ.title}</h2>
            <p className="veyra-lede mx-auto mt-4 text-pretty text-veyra-muted">{FAQ.body}</p>
          </div>
        </Reveal>

        {/* The container reveals as one card. Individual rows are not
            animated: the accordion already has its own open/close motion and
            two motion systems on the same element would fight each other. */}
        <Reveal
          delay={100}
          className="veyra-card-glow veyra-section-body relative isolate mx-auto max-w-[840px] overflow-hidden rounded-[24px] border border-veyra-cream/[0.14] bg-veyra-ink-raised"
        >
          <dl className="relative divide-y divide-veyra-cream/10 px-5 sm:px-6">
            {FAQ.items.map((item, index) => {
              const open = openIndex === index;
              const panelId = `faq-panel-${index}`;
              return (
                <div key={item.question}>
                  <dt>
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-controls={panelId}
                      onClick={() => setOpenIndex(open ? null : index)}
                      className="flex min-h-[72px] w-full items-center justify-between gap-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink-raised"
                    >
                      <span className="text-[1.0625rem] font-semibold tracking-[-0.02em] text-veyra-cream sm:text-[1.125rem]">
                        {item.question}
                      </span>
                      {open ? (
                        <X className="h-[18px] w-[18px] shrink-0 text-veyra-sand" aria-hidden="true" />
                      ) : (
                        <Plus
                          className="h-[18px] w-[18px] shrink-0 text-veyra-muted-dark"
                          aria-hidden="true"
                        />
                      )}
                    </button>
                  </dt>
                  {/* `hidden` is gone: it cannot be transitioned. The panel
                      animates on grid-template-rows instead, which needs no
                      hardcoded max-height and so can never clip a long answer.
                      Assistive technology still gets the state from
                      aria-expanded on the control above. */}
                  <dd id={panelId} className="veyra-faq-panel" data-open={open}>
                    <div>
                      <p className="max-w-[650px] pb-6 pr-6 text-[0.9375rem] leading-[1.65] text-veyra-muted sm:pr-10 sm:text-base">
                        {item.answer}
                      </p>
                    </div>
                  </dd>
                </div>
              );
            })}
          </dl>
        </Reveal>
      </div>
    </section>
  );
}
