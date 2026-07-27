import { Separator } from "@/components/ui/separator";
import Image from "next/image";

export function Footer() {
  return (
    <footer className="w-full border-t bg-background">
      <div className="container mx-auto py-8 md:py-10">
        <div className="flex flex-col items-center justify-between gap-4 md:flex-row">
          <div className="flex items-center gap-2">
            <Image src="/veyra-logo.svg" alt="Veyra" width={44} height={44} className="rounded-md" />
            <div>
              <p className="font-bold">Veyra</p>
              <p className="text-sm text-muted-foreground">Autonomous work. Verified outcomes. USDC settlement.</p>
            </div>
          </div>
          <p className="text-sm text-muted-foreground">Arc Testnet · Circle User-Controlled Wallets</p>
        </div>
        <Separator className="my-6" />
        <p className="text-center text-xs text-muted-foreground">© {new Date().getFullYear()} Veyra. All rights reserved.</p>
      </div>
    </footer>
  );
}
