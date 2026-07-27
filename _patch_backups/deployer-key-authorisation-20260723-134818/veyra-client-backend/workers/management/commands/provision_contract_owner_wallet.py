from django.core.management.base import BaseCommand, CommandError

from workers.platform_owner_wallet import (
    PlatformOwnerWalletError,
    persist_platform_owner_wallet_to_env,
    provision_platform_owner_wallet,
)


class Command(BaseCommand):
    help = (
        "Create or reuse the dedicated Circle developer-controlled wallet that "
        "will own VeyraJobEscrow, then persist its non-secret ID and address."
    )

    def handle(self, *args, **options):
        try:
            result = provision_platform_owner_wallet()
            env_path, backup_path = persist_platform_owner_wallet_to_env(result)
        except PlatformOwnerWalletError as exc:
            raise CommandError(str(exc)) from exc

        action = "created" if result.created else "reused"
        self.stdout.write(self.style.SUCCESS(f"Platform owner wallet {action}."))
        self.stdout.write(f"Wallet ID: {result.wallet_id}")
        self.stdout.write(f"Address: {result.address}")
        self.stdout.write(f"Blockchain: {result.blockchain}")
        self.stdout.write(f"Account type: {result.account_type}")
        self.stdout.write(f"Updated env: {env_path}")
        self.stdout.write(f"Env backup: {backup_path}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "Restart the Django process before running the ownership acceptance command."
            )
        )
        self.stdout.write(
            "The wallet ID and address are identifiers, not private keys."
        )
