from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand

from blockchain.indexer import scan_once
from workers.execution_orchestrator import orchestrate_execution_once


class Command(BaseCommand):
    help = "Run Veyra's automatic matching, claim, execution, verification, and settlement control plane."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one orchestration cycle and exit.")
        parser.add_argument("--interval", type=int, default=5, help="Seconds between watch cycles.")
        parser.add_argument("--skip-indexer", action="store_true", help="Do not scan Arc events in this process.")

    def handle(self, *args, **options):
        once = bool(options["once"])
        interval = max(2, int(options["interval"]))
        skip_indexer = bool(options["skip_indexer"])
        self.stdout.write(self.style.SUCCESS("Veyra execution layer started."))
        while True:
            if not skip_indexer:
                try:
                    scan_once()
                except Exception as exc:
                    self.stderr.write(f"Arc indexer cycle deferred: {str(exc)[:500]}")
            try:
                result = orchestrate_execution_once()
                self.stdout.write(json.dumps(result.as_dict(), sort_keys=True))
            except Exception as exc:
                self.stderr.write(f"Execution cycle failed safely: {str(exc)[:800]}")
            if once:
                return
            time.sleep(interval)
