"use client";

import { cn } from "@/lib/utils";
import { useEffect, useRef } from "react";


/**
 * Landing entrance system.
 *
 * Three deliberate constraints shape this file:
 *
 * 1. Progressive enhancement. The server renders every child fully visible.
 *    The hidden pre-reveal state is armed only by `.veyra-motion`, which is
 *    added to the landing root after hydration. If JavaScript never runs the
 *    page is simply a finished, static page.
 *
 * 2. One observer. A single module-level IntersectionObserver serves every
 *    revealed element on the page, rather than one observer per component.
 *
 * 3. No React state during scroll. Revealing toggles a class directly on the
 *    DOM node and then unobserves it. Scrolling never triggers a re-render,
 *    and no element is ever re-hidden on the way back up.
 */

const REVEAL_CLASS = "veyra-revealed";
const DONE_CLASS = "veyra-reveal-done";

/** Longest transition (720ms) plus the largest stagger we apply. */
const CLEANUP_DELAY_MS = 1200;

let observer: IntersectionObserver | null = null;

function prefersReducedMotion() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function getObserver() {
  if (typeof window === "undefined") return null;
  if (observer) return observer;
  if (typeof IntersectionObserver === "undefined") return null;

  observer = new IntersectionObserver(
    (entries, self) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;

        const el = entry.target as HTMLElement;
        el.classList.add(REVEAL_CLASS);

        /* Reveal once. Unobserving here is what stops the element from
           being hidden again when the user scrolls back up. */
        self.unobserve(el);

        /* Drop the compositor hint once the transition has finished so a
           long page does not keep dozens of promoted layers alive. */
        window.setTimeout(() => el.classList.add(DONE_CLASS), CLEANUP_DELAY_MS);
      }
    },
    { threshold: 0.16, rootMargin: "0px 0px -10% 0px" },
  );

  return observer;
}

/**
 * The landing root.
 *
 * Renders the same markup on the server and on the first client paint, then
 * adds `veyra-motion` in an effect. That class is the switch which arms every
 * pre-reveal state in the stylesheet, so:
 *
 *   - no JavaScript  -> class never added -> everything visible
 *   - reduced motion -> class never added -> everything visible
 *   - no IO support  -> class never added -> everything visible
 *
 * Because the class is added after hydration rather than during render, there
 * is no server/client markup mismatch.
 */
export function LandingMotionRoot({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (prefersReducedMotion()) return;
    if (typeof IntersectionObserver === "undefined") return;

    node.classList.add("veyra-motion");
    return () => node.classList.remove("veyra-motion");
  }, []);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}


type RevealProps = {
  children: React.ReactNode;
  className?: string;
  /** Stagger, in milliseconds, applied as a CSS transition-delay. */
  delay?: number;
  /** Directional entry. Horizontal variants flatten to vertical below lg. */
  variant?: "up" | "tight" | "left" | "right" | "panel" | "rail";

  /** Render something other than a div, e.g. an li inside a list. */
  as?: "div" | "li" | "section" | "article" | "span";
  /** Preserved so anchor targets keep working when Reveal renders the element. */
  id?: string;
};


const VARIANT_CLASS: Record<NonNullable<RevealProps["variant"]>, string> = {
  up: "",
  tight: "veyra-reveal-tight",
  left: "veyra-reveal-left",

  right: "veyra-reveal-right",
  panel: "veyra-reveal-panel",
  rail: "veyra-reveal-rail",
};

/**
 * Wraps content in a single reveal step.
 *
 * The element is registered with the shared observer on mount. If reduced
 * motion is on, or IntersectionObserver is unavailable, it registers nothing
 * and the content simply stays visible.
 */
export function Reveal({
  children,
  className,
  delay = 0,
  variant = "up",
  as: Tag = "div",
  id,
}: RevealProps) {

  /* Rendered identically on server and first client paint, so hydration
     matches; the observer attaches in the effect that follows. */
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const node = ref.current;

    if (!node) return;
    if (prefersReducedMotion()) return;

    const io = getObserver();
    if (!io) return;

    /* Already on screen at mount (above the fold): reveal on the next frame
       so the browser still sees a start state and animates the change. */
    io.observe(node);

    return () => io.unobserve(node);
  }, []);

  return (
    <Tag
      ref={ref as React.RefObject<never>}
      className={cn("veyra-reveal", VARIANT_CLASS[variant], className)}
      style={delay ? ({ "--veyra-reveal-delay": `${delay}ms` } as React.CSSProperties) : undefined}
      {...(id ? { id } : {})}
    >
      {children}
    </Tag>
  );
}


