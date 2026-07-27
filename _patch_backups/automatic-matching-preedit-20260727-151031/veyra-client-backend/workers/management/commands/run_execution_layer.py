from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand

from workers.execution_orchestrator import orchestrate_execution_once


class Command(BaseCommand):
    help = "Run Veyra's automatic matching, claim, execution, verification, and settlement control plane."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one orchestration cycle and exit.")
        parser.add_argument("--interval", type=int, default=5, help="Seconds between watch cycles.")

    def handle(self, *args, **options):
        once = bool(options["once"])
        interval = max(2, int(options["interval"]))
        self.stdout.write(
            self.style.SUCCESS(
                "Veyra execution layer started with targeted transaction reconciliation."
            )
        )
        while True:
            try:
                # The orchestrator reconciles only known job actions using their
                # stored Circle transaction IDs and exact Arc transaction hashes.
                # It does not scan the chain or poll unrelated blocks.
                result = orchestrate_execution_once()
                self.stdout.write(json.dumps(result.as_dict(), sort_keys=True))
            except Exception as exc:
                self.stderr.write(f"Execution cycle failed safely: {str(exc)[:800]}")
            if once:
                return
            time.sleep(interval)
