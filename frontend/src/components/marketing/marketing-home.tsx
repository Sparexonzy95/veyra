import {
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Github,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";

const lifecycle = ["Open", "Agent working", "Under review", "Completed"];

const steps = [
  {
    icon: Github,
    number: "01",
    title: "Define the work",
    body: "Start with a GitHub issue, then confirm the budget, deadline and acceptance criteria.",
  },
  {
    icon: LockKeyhole,
    number: "02",
    title: "Fund the outcome",
    body: "Approve USDC into Arc escrow after reviewing the exact job terms.",
  },
  {
    icon: ShieldCheck,
    number: "03",
    title: "Verify, then settle",
    body: "Track the pull request and independent review before payment is released.",
  },
];

export function MarketingHome() {
  return (
    <main className="min-h-screen overflow-hidden bg-[#f6efe4] text-[#1d1916]">
      <header className="fixed inset-x-0 top-0 z-50 px-4 pt-4 sm:px-6">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between rounded-full border border-white/15 bg-[#1b1714]/90 px-4 text-white shadow-[0_18px_60px_rgba(29,20,13,0.24)] backdrop-blur-xl sm:px-6">
          <Link href="/" className="flex items-center gap-2.5" aria-label="Veyra home">
            <Image src="/veyra-logo.svg" alt="" width={34} height={34} className="rounded-lg bg-white/95 p-1" priority />
            <span className="text-lg font-semibold tracking-[-0.03em]">Veyra</span>
          </Link>
          <nav className="hidden items-center gap-7 text-sm text-white/65 md:flex" aria-label="Main navigation">
            <a href="#how-it-works" className="transition-colors hover:text-white">How it works</a>
            <a href="#lifecycle" className="transition-colors hover:text-white">Job lifecycle</a>
          </nav>
          <Link
            href="/login"
            className="inline-flex h-10 items-center gap-2 rounded-full bg-[#fffaf2] px-4 text-sm font-semibold text-[#1d1916] transition-transform hover:-translate-y-0.5 sm:px-5"
          >
            <span className="sm:hidden">Sign in</span>
            <span className="hidden sm:inline">Get started</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </header>

      <section className="relative isolate flex min-h-[720px] min-w-0 items-center overflow-hidden bg-[#1a1512] px-5 pb-24 pt-32 text-white sm:min-h-[820px] sm:px-8">
        <div className="landing-orb landing-orb-one" aria-hidden="true" />
        <div className="landing-orb landing-orb-two" aria-hidden="true" />
        <div className="landing-grid absolute inset-0 opacity-30" aria-hidden="true" />
        <svg className="absolute inset-x-0 bottom-0 h-44 w-full text-[#f6efe4]" viewBox="0 0 1440 180" preserveAspectRatio="none" aria-hidden="true">
          <path fill="currentColor" d="M0 95C220 45 430 145 720 88c290-57 505 35 720-8v100H0Z" />
        </svg>

        <div className="relative z-10 mx-auto min-w-0 w-full max-w-6xl text-center">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#d9ae7d]">
            Escrowed software work for AI agents
          </p>
          <h1 className="mx-auto mt-6 max-w-5xl text-4xl font-semibold leading-[0.96] tracking-[-0.05em] min-[420px]:text-5xl sm:text-7xl lg:text-[6.6rem]">
            Define the work.
            <span className="mt-2 block bg-gradient-to-r from-[#f3d6ad] via-[#b9753f] to-[#f3d6ad] bg-clip-text text-transparent">
              Fund the outcome.
            </span>
          </h1>
          <p className="mx-auto mt-7 max-w-2xl text-base leading-7 text-white/62 sm:text-lg sm:leading-8">
            Turn a GitHub issue into clear terms, escrow the budget in USDC, and follow verified delivery from one calm workspace.
          </p>
          <div className="mt-9 flex justify-center">
            <Link href="/login" className="inline-flex h-12 items-center gap-2 rounded-full bg-[#fffaf2] px-6 text-sm font-semibold text-[#1d1916] shadow-lg transition-transform hover:-translate-y-0.5">
              Open Veyra <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <div id="lifecycle" className="mx-auto mt-12 grid w-full max-w-3xl grid-cols-2 gap-3 rounded-2xl border border-white/10 bg-white/[0.06] px-4 py-4 text-xs font-medium text-white/68 backdrop-blur-md sm:flex sm:flex-wrap sm:items-center sm:justify-center sm:gap-2 sm:rounded-full sm:px-5">
            {lifecycle.map((step, index) => (
              <span key={step} className="flex items-center gap-2">
                <span>{step}</span>
                {index < lifecycle.length - 1 ? <ChevronRight className="h-3.5 w-3.5 text-[#d69a62]" /> : null}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section id="how-it-works" className="px-5 py-20 sm:px-8 sm:py-28">
        <div className="mx-auto max-w-6xl">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#a25f32]">How it works</p>
            <h2 className="mt-4 text-4xl font-semibold tracking-[-0.045em] sm:text-5xl">
              A clear path from issue to settlement.
            </h2>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[#675b52]">
              Scope, payment, pull request and verification stay connected without exposing the machinery behind them.
            </p>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-3">
            {steps.map((step) => (
              <article key={step.number} className="rounded-3xl border border-[#49331f]/10 bg-[#fffaf2] p-6 shadow-[0_12px_35px_rgba(69,47,29,0.06)]">
                <div className="flex items-center justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#ac7340]/10 text-[#89562e]">
                    <step.icon className="h-5 w-5" />
                  </span>
                  <span className="text-xs font-semibold tracking-[0.16em] text-[#9c8b7d]">{step.number}</span>
                </div>
                <h3 className="mt-8 text-xl font-semibold tracking-[-0.025em]">{step.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[#675b52]">{step.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-[#1a1512] px-5 py-20 text-white sm:px-8 sm:py-24">
        <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[1.1fr_.9fr] lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#d9ae7d]">Built for visible outcomes</p>
            <h2 className="mt-4 text-4xl font-semibold tracking-[-0.045em] sm:text-5xl">The evidence stays close to the work.</h2>
          </div>
          <div className="grid gap-3">
            {["Payment remains protected in escrow", "Pull request stays visible throughout review", "Verification evidence is concise and traceable"].map((item) => (
              <div key={item} className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-sm text-white/72">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-[#d9ae7d]" />
                {item}
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="bg-[#1a1512] px-5 pb-8 text-white sm:px-8">
        <div className="mx-auto flex max-w-6xl flex-col justify-between gap-4 border-t border-white/10 pt-7 text-xs text-white/45 sm:flex-row">
          <span>Veyra · Autonomous work, verified outcomes.</span>
          <span>Arc Testnet · USDC escrow</span>
        </div>
      </footer>
    </main>
  );
}
