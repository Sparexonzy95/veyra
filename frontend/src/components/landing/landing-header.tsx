"use client";

import { NAV_LINKS } from "@/components/landing/landing-content";
import { VeyraWordmark } from "@/components/landing/veyra-wordmark";
import { cn } from "@/lib/utils";
import { ArrowRight, Menu, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

/**
 * Dark glass navbar.
 *
 * Fixed, centred and rounded. The surface is translucent ink rather than a
 * cream plate, so it reads as glass over both the ink sections and the
 * luminous lower hero.
 */
export function LandingHeader() {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  /* Escape closes and returns focus to the trigger. */
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

  /* Lock body scroll while the menu covers the viewport, then restore it. */
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  /* Keep focus inside the open panel so the menu is not a keyboard trap
     in either direction: Tab cycles, Escape leaves. */
  const onPanelKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab") return;
    const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled])',
    );
    if (!focusables || focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <header className="fixed inset-x-0 top-3 z-50 md:top-4">
      <div className="veyra-nav-shell">
        <nav
          aria-label="Primary"
          className={cn(
            "veyra-nav-glass flex h-[56px] items-center justify-between rounded-full pl-4 pr-2 md:h-[62px] md:pl-5 md:pr-2.5",
          )}
        >
          <Link
            href="/"
            aria-label="Veyra home"
            className="flex shrink-0 items-center rounded-full py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink-raised"
          >
            <VeyraWordmark
              uid="nav"
              color="var(--veyra-cream)"
              className="w-[96px] md:w-[112px]"
            />
          </Link>

          {/* Desktop links. Gaps tighten on tablet before anything is hidden. */}
          <div className="hidden items-center gap-[18px] lg:flex lg:gap-[26px] xl:gap-[30px] min-[900px]:flex">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="veyra-nav-link whitespace-nowrap rounded-full py-2 text-veyra-muted transition-colors duration-200 hover:text-veyra-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink-raised motion-reduce:transition-none"
              >
                {link.label}
              </a>
            ))}
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <Link
              href="/login"
              className="group hidden h-11 items-center gap-2 rounded-full border border-veyra-cream bg-veyra-cream px-5 text-sm font-semibold leading-none text-veyra-ink transition-colors duration-200 hover:bg-veyra-cream-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink-raised disabled:pointer-events-none disabled:opacity-60 motion-reduce:transition-none sm:inline-flex md:px-[22px]"
            >
              Get Started
              <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-[3px] motion-reduce:transition-none motion-reduce:group-hover:translate-x-0" aria-hidden="true" />
            </Link>

            <button
              ref={triggerRef}
              type="button"
              onClick={() => (open ? close() : setOpen(true))}
              aria-expanded={open}
              aria-controls={menuId}
              aria-label={open ? "Close menu" : "Open menu"}
              className="inline-flex h-11 w-11 items-center justify-center rounded-full text-veyra-cream transition-colors duration-200 hover:bg-veyra-cream/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink-raised motion-reduce:transition-none min-[900px]:hidden"
            >
              {open ? (
                <X className="h-5 w-5" aria-hidden="true" />
              ) : (
                <Menu className="h-5 w-5" aria-hidden="true" />
              )}
            </button>
          </div>
        </nav>

        {/* Mobile menu. Rendered inside the header so it overlays rather than
            shifting the page, and constrained to the viewport height. */}
        {open ? (
          <div
            id={menuId}
            ref={panelRef}
            onKeyDown={onPanelKeyDown}
            className="veyra-nav-glass mt-2 max-h-[calc(100dvh-96px)] overflow-y-auto rounded-3xl p-3 min-[900px]:hidden"
          >
            <ul className="flex flex-col">
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <a
                    href={link.href}
                    onClick={() => close(false)}
                    className="flex min-h-[48px] items-center rounded-2xl px-4 text-[0.9375rem] font-medium text-veyra-muted transition-colors duration-200 hover:bg-veyra-cream/10 hover:text-veyra-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream motion-reduce:transition-none"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>

            <Link
              href="/login"
              onClick={() => close(false)}
              className="mt-2 inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-veyra-cream px-5 text-sm font-semibold text-veyra-ink transition-colors duration-200 hover:bg-veyra-cream-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-veyra-cream focus-visible:ring-offset-2 focus-visible:ring-offset-veyra-ink-raised disabled:pointer-events-none disabled:opacity-60 motion-reduce:transition-none sm:hidden"
            >
              Get Started
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
        ) : null}
      </div>
    </header>
  );
}
