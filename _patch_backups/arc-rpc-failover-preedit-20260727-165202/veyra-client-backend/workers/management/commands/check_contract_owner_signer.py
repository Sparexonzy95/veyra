from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from web3 import Web3

from blockchain.client import ArcClient


class Command(BaseCommand):
    help = "Verify that the configured private key matches VeyraJobEscrow.owner()."

    def handle(self, *args, **options):
        private_key = str(
            getattr(settings, "VEYRA_CONTRACT_OWNER_PRIVATE_KEY", "") or ""
        ).strip()
        if not private_key:
            raise CommandError("VEYRA_CONTRACT_OWNER_PRIVATE_KEY is not configured.")

        arc = ArcClient()
        try:
            arc.assert_chain()
            signer = arc.w3.eth.account.from_key(private_key)
            signer_address = Web3.to_checksum_address(signer.address)
            owner = Web3.to_checksum_address(
                arc.contract.functions.owner().call()
            )
            balance = arc.w3.eth.get_balance(signer_address)
        except Exception as exc:
            raise CommandError(f"Could not verify contract-owner signer: {exc}") from exc

        self.stdout.write(f"Contract: {settings.VEYRA_CONTRACT_ADDRESS}")
        self.stdout.write(f"Configured signer: {signer_address}")
        self.stdout.write(f"On-chain owner: {owner}")
        self.stdout.write(f"Native gas balance: {balance}")

        if signer_address != owner:
            raise CommandError(
                "The configured private key does not belong to the contract owner."
            )
        self.stdout.write(
            self.style.SUCCESS("The deployer private key matches the contract owner.")
        )
