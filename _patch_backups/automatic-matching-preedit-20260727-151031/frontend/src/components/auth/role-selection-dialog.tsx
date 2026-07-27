"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Bot, Building2 } from "lucide-react";
import { useState } from "react";

export function RoleSelectionDialog() {
  const {
    roleDialogOpen,
    chooseClientRole,
    chooseAgentOwnerRole,
    busy,
  } = useVeyra();
  const [selected, setSelected] = useState<"CLIENT" | "AGENT_OWNER" | null>(null);

  async function continueWithRole() {
    if (selected === "CLIENT") {
      await chooseClientRole();
      return;
    }
    if (selected === "AGENT_OWNER") {
      await chooseAgentOwnerRole();
    }
  }

  return (
    <Dialog open={roleDialogOpen}>
      <DialogContent className="sm:max-w-[560px]" hideCloseButton>
        <DialogHeader>
          <DialogTitle>How will you use Veyra?</DialogTitle>
          <DialogDescription>
            Choose your first workspace. You can hold both roles later.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <button
            type="button"
            className={`relative w-full cursor-pointer rounded-xl border-2 p-6 text-left transition-all ${
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
            className={`relative w-full cursor-pointer rounded-xl border-2 p-6 text-left transition-all ${
              selected === "AGENT_OWNER"
                ? "border-primary-500 bg-primary-500/5"
                : "border-border hover:border-primary-500/50"
            }`}
            onClick={() => setSelected("AGENT_OWNER")}
          >
            <div className="flex items-start gap-4">
              <Bot className="mt-1 h-8 w-8" />
              <div>
                <h3 className="text-lg font-semibold">Run an Agent</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Create Veyra-hosted coding agents. Each agent receives its own
                  operational Arc wallet and earns USDC separately.
                </p>
              </div>
            </div>
          </button>
        </div>
        <div className="flex justify-end gap-3">
          <Button
            onClick={() => void continueWithRole()}
            disabled={!selected || busy}
            className="min-w-[120px]"
          >
            {busy ? "Setting up..." : "Continue"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
