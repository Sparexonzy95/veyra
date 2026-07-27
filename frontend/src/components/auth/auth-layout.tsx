import { Card, CardContent } from "@/components/ui/card";
import Image from "next/image";
import Link from "next/link";

export function AuthLayout({
  children,
  title,
  description,
}: {
  children: React.ReactNode;
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col gap-6">
      <Card className="overflow-hidden border-[#6f4a2d]/15 shadow-[0_24px_80px_rgba(61,39,24,0.10)]">
        <CardContent className="grid grid-cols-1 p-0 md:grid-cols-[1.05fr_.95fr]">
          <div className="p-7 sm:p-9">
            <div className="flex flex-col gap-6">
              <div className="flex flex-col items-center justify-center gap-4 text-center">
                <Link href="/">
                  <Image src="/veyra-logo.svg" alt="Veyra" width={76} height={76} />
                </Link>
                <div className="flex flex-col">
                  <h1 className="text-3xl font-semibold tracking-[-0.035em]">{title}</h1>
                  {description ? (
                    <p className="mt-1 text-balance text-sm text-muted-foreground">{description}</p>
                  ) : null}
                </div>
              </div>
              {children}
            </div>
          </div>
          <div className="relative hidden min-h-[430px] overflow-hidden bg-[#1a1512] p-8 text-white md:flex md:flex-col md:justify-between">
            <div className="landing-grid absolute inset-0 opacity-40" aria-hidden="true" />
            <div className="landing-orb landing-orb-two" aria-hidden="true" />
            <p className="relative text-xs font-semibold uppercase tracking-[0.18em] text-[#d9ae7d]">Veyra workspace</p>
            <div className="relative">
              <p className="text-3xl font-semibold leading-tight tracking-[-0.04em]">Fund clear work.<br />Follow verified outcomes.</p>
              <p className="mt-4 text-sm leading-6 text-white/58">Payment, pull request and independent review stay connected.</p>
            </div>
          </div>
        </CardContent>
      </Card>
      <div className="text-balance text-center text-xs text-muted-foreground">
        Autonomous work. Verified outcomes. USDC settlement.
      </div>
    </div>
  );
}
