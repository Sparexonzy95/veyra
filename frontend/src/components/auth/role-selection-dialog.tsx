"use client";

import { useVeyra } from "@/components/providers/veyra-provider";
import { VeyraChoice } from "@/components/auth/veyra-choice";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Signup actor choice. Renders the same `VeyraChoice` component as
 * `/workspace`, so there is one design to maintain rather than two.
 */
export function RoleSelectionDialog() {
  const {
    roleDialogOpen,
    chooseClientRole,
    chooseAgentOwnerRole,
    busy,
    me,
  } = useVeyra();

  const hasClient = Boolean(me?.capabilities?.includes("CLIENT"));
  const hasAgentOwner = Boolean(me?.capabilities?.includes("AGENT_OWNER"));

  return (
    <Dialog open={roleDialogOpen}>
      <DialogContent
        className="veyra-scope border-veyra-cream/10 bg-veyra-ink p-6 text-veyra-cream shadow-[0_28px_90px_rgba(0,0,0,0.55)] sm:max-w-[720px]"
        hideCloseButton
      >
        <DialogHeader>
          <DialogTitle className="text-xl tracking-[-0.02em] text-veyra-cream">
            How will you use Veyra?
          </DialogTitle>
          <DialogDescription className="text-sm text-veyra-muted">
            Your account can use both sides.
          </DialogDescription>
        </DialogHeader>
        <div className="pt-2">
          <VeyraChoice
            compact
            busy={busy}
            hasMaintainer={hasClient}
            hasAgentOwner={hasAgentOwner}
            onChooseMaintainer={() => void chooseClientRole()}
            onChooseAgentOwner={() => void chooseAgentOwnerRole()}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
