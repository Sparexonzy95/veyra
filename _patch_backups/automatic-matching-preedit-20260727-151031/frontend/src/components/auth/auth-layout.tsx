import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
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
      <Card className="overflow-hidden">
        <CardContent className="grid grid-cols-1 p-0">
          <div className="p-6 md:p-8">
            <div className="flex flex-col gap-6">
              <div className="flex flex-col items-center justify-center gap-4 text-center md:flex-row">
                <Link href="/">
                  <Image src="/veyra-logo.svg" alt="Veyra" width={120} height={120} />
                </Link>
                <Separator orientation="vertical" className="mx-4 hidden h-32 bg-gray-400 md:block" />
                <div className="flex flex-col">
                  <h1 className="text-2xl font-bold">{title}</h1>
                  {description ? (
                    <p className="text-balance text-muted-foreground">{description}</p>
                  ) : null}
                </div>
              </div>
              {children}
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
