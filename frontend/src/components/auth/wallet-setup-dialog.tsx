"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Loader2, ShieldCheck } from "lucide-react";

export function WalletSetupDialog() {
  const { walletSetupOpen, status } = useVeyra();
  return (
    <Dialog open={walletSetupOpen}>
      <DialogContent className="sm:max-w-[460px]" hideCloseButton>
        <DialogHeader>
          <DialogTitle>Preparing your wallet</DialogTitle>
          <DialogDescription>
            Veyra is creating your secure Arc Testnet wallet through Circle.
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-4 rounded-lg border p-5">
          <div className="rounded-full bg-primary-50 p-3 text-primary-700">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div className="flex-1">
            <p className="font-medium">{status ?? "Setting up your secure Veyra wallet…"}</p>
            <p className="mt-1 text-sm text-muted-foreground">No seed phrase or browser wallet is required.</p>
          </div>
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
        </div>
      </DialogContent>
    </Dialog>
  );
}
