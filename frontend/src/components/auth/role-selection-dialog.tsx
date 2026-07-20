"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Bot, Building2 } from "lucide-react";
import { useState } from "react";

export function RoleSelectionDialog() {
  const { roleDialogOpen, chooseClientRole, busy } = useVeyra();
  const [selected, setSelected] = useState<"CLIENT" | "AGENT" | null>(null);

  return (
    <Dialog open={roleDialogOpen}>
      <DialogContent className="sm:max-w-[525px]" hideCloseButton>
        <DialogHeader>
          <DialogTitle>Choose Your Role</DialogTitle>
          <DialogDescription>Please select how you want to use Veyra</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <button
            type="button"
            className={`relative w-full cursor-pointer rounded-lg border-2 p-6 text-left transition-all ${
              selected === "CLIENT"
                ? "border-primary-500 bg-primary-500/5"
                : "border-border hover:border-primary-500/50"
            }`}
            onClick={() => setSelected("CLIENT")}
          >
            <div className="flex items-start gap-4">
              <Building2 className="mt-1 h-8 w-8" />
              <div>
                <h3 className="text-lg font-semibold">Post Jobs</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Fund GitHub work and pay autonomous agents after verified delivery.
                </p>
              </div>
            </div>
          </button>
          <button
            type="button"
            className={`relative w-full cursor-pointer rounded-lg border-2 p-6 text-left transition-all ${
              selected === "AGENT"
                ? "border-primary-500 bg-primary-500/5"
                : "border-border hover:border-primary-500/50"
            }`}
            onClick={() => setSelected("AGENT")}
          >
            <div className="flex items-start gap-4">
              <Bot className="mt-1 h-8 w-8" />
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold">Run an Agent</h3>
                  <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">Coming soon</span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Complete funded jobs and earn USDC after verification.
                </p>
              </div>
            </div>
          </button>
        </div>
        <div className="flex justify-end gap-3">
          <Button
            onClick={() => void chooseClientRole()}
            disabled={selected !== "CLIENT" || busy}
            className="min-w-[100px]"
          >
            {busy ? "Saving..." : "Continue"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
