from __future__ import annotations

import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from web3 import Web3

from blockchain.client import ArcClient
from workers.contract_authorisation import (
    CircleContractOwnerClient,
    ContractAuthorisationError,
)


class Command(BaseCommand):
    help = "Accept pending VeyraJobEscrow ownership from the Circle platform wallet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--transaction-id",
            default="",
            help="Reconcile an already-created Circle transaction instead of creating another.",
        )

    def handle(self, *args, **options):
        wallet_id = str(
            getattr(settings, "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_ID", "") or ""
        ).strip()
        owner_address = str(
            getattr(settings, "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS", "") or ""
        ).strip()
        if not wallet_id or not owner_address:
            raise CommandError(
                "Provision the Circle platform owner wallet first."
            )
        if not Web3.is_address(owner_address):
            raise CommandError("Configured platform owner address is invalid.")

        owner_address = Web3.to_checksum_address(owner_address)
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

        if current == owner_address:
            self.stdout.write(
                self.style.SUCCESS("The Circle platform wallet already owns the contract.")
            )
            return
        if pending != owner_address:
            raise CommandError(
                "The configured Circle platform wallet is not the pending owner. "
                "Run the Hardhat transfer-ownership step first."
            )

        try:
            circle = CircleContractOwnerClient()
            transaction_id = str(options.get("transaction_id") or "").strip()
            if transaction_id:
                snapshot = circle.get_transaction(transaction_id)
            else:
                snapshot = circle.create_contract_call(
                    owner_wallet_id=wallet_id,
                    function_signature="acceptOwnership()",
                    abi_parameters=[],
                    idempotency_key=uuid.uuid4(),
                )
                transaction_id = snapshot["id"]
                self.stdout.write(f"Circle transaction ID: {transaction_id}")

            terminal = {"COMPLETE", "FAILED", "CANCELLED", "DENIED"}
            timeout = int(
                getattr(settings, "VEYRA_CONTRACT_AUTHORISATION_TIMEOUT_SECONDS", 180)
            )
            interval = max(
                1,
                int(
                    getattr(
                        settings,
                        "VEYRA_CONTRACT_AUTHORISATION_POLL_INTERVAL_SECONDS",
                        3,
                    )
                ),
            )
            deadline = time.monotonic() + timeout
            while snapshot["state"] not in terminal and time.monotonic() < deadline:
                time.sleep(interval)
                snapshot = circle.get_transaction(transaction_id)

            if snapshot["state"] != "COMPLETE":
                raise CommandError(
                    f"Circle ownership acceptance is {snapshot['state']}. "
                    f"Re-run with --transaction-id {transaction_id}."
                )
        except ContractAuthorisationError as exc:
            raise CommandError(str(exc)) from exc

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            current = Web3.to_checksum_address(
                arc.contract.functions.owner().call()
            )
            if current == owner_address:
                self.stdout.write(
                    self.style.SUCCESS(
                        "The Circle platform wallet now owns VeyraJobEscrow."
                    )
                )
                if snapshot.get("tx_hash"):
                    self.stdout.write(f"Arc transaction: {snapshot['tx_hash']}")
                return
            time.sleep(3)

        raise CommandError(
            "Circle completed the transaction, but Arc has not reflected ownership yet."
        )
