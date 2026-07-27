from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from web3 import Web3

from blockchain.client import ArcClient


class Command(BaseCommand):
    help = "Show current and pending VeyraJobEscrow ownership."

    def handle(self, *args, **options):
        arc = ArcClient()
        try:
            arc.assert_chain()
            current = Web3.to_checksum_address(
                arc.contract.functions.owner().call()
            )
            pending = Web3.to_checksum_address(
                arc.contract.functions.pendingOwner().call()
            )
        except Exception as exc:
            raise CommandError(f"Could not read contract ownership: {exc}") from exc

        configured = str(
            getattr(settings, "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS", "") or ""
        ).strip()
        wallet_id = str(
            getattr(settings, "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_ID", "") or ""
        ).strip()

        self.stdout.write(f"Contract: {settings.VEYRA_CONTRACT_ADDRESS}")
        self.stdout.write(f"Current owner: {current}")
        self.stdout.write(f"Pending owner: {pending}")
        self.stdout.write(f"Configured Circle owner: {configured or '(missing)'}")
        self.stdout.write(f"Configured Circle wallet ID: {wallet_id or '(missing)'}")

        if configured and current.lower() == configured.lower():
            self.stdout.write(self.style.SUCCESS("Circle platform wallet owns the contract."))
        elif configured and pending.lower() == configured.lower():
            self.stdout.write(
                self.style.WARNING(
                    "Ownership transfer is pending. Run accept_contract_ownership."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Ownership has not been transferred to the configured Circle wallet."
                )
            )
