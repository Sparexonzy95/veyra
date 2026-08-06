import { RoleSelectionDialog } from "@/components/auth/role-selection-dialog";
import { WalletSetupDialog } from "@/components/auth/wallet-setup-dialog";

export function GlobalAuthDialogs() {
  return (
    <>
      <RoleSelectionDialog />
      <WalletSetupDialog />
    </>
  );
}
