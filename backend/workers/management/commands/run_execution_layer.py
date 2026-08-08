from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

from workers.execution_control import (
    claim_controller,
    finish_cycle,
    log_event,
    release_controller,
    start_cycle,
)
from workers.execution_orchestrator import orchestrate_execution_once


class Command(BaseCommand):
    help = "Run Veyra's automatic matching, claim, execution, verification, and settlement control plane."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one orchestration cycle and exit.")
        parser.add_argument("--interval", type=int, default=5, help="Seconds between watch cycles.")
        parser.add_argument(
            "--max-interval",
            type=int,
            default=120,
            help="Maximum retry delay after consecutive cycle failures.",
        )

    def handle(self, *args, **options):
        once = bool(options["once"])
        interval = max(2, int(options["interval"]))
        maximum_interval = max(interval, int(options["max_interval"]))
        try:
            instance_id = claim_controller()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Veyra execution layer started with targeted transaction reconciliation."
            )
        )
        consecutive_failures = 0
        try:
            while True:
                cycle_number = start_cycle(instance_id)
                log_event("cycle_started", cycle=cycle_number)
                try:
                    # The orchestrator reconciles only known job actions using
                    # stored transaction IDs and exact Arc hashes. It never
                    # scans unrelated blocks.
                    result = orchestrate_execution_once(cycle_number=cycle_number)
                    payload = result.as_dict()
                    consecutive_failures = 0
                    delay = interval
                    finish_cycle(
                        instance_id,
                        delay_seconds=delay,
                        result=payload,
                    )
                    log_event(
                        "cycle_finished",
                        cycle=cycle_number,
                        result=payload,
                        next_retry_seconds=delay,
                    )
                    self.stdout.write(json.dumps(payload, sort_keys=True))
                except Exception as exc:
                    consecutive_failures += 1
                    delay = min(
                        maximum_interval,
                        interval * (2 ** min(consecutive_failures - 1, 8)),
                    )
                    finish_cycle(
                        instance_id,
                        delay_seconds=delay,
                        error=exc,
                        consecutive_failures=consecutive_failures,
                    )
                    log_event(
                        "cycle_failed",
                        cycle=cycle_number,
                        error_type=exc.__class__.__name__,
                        next_retry_seconds=delay,
                    )
                    self.stderr.write(
                        self.style.ERROR(
                            "Execution cycle failed safely; automatic retry "
                            f"in {delay}s. See the structured traceback log."
                        )
                    )
                    self.stderr.write(self.style.ERROR(str(exc)[:800]))
                    import logging

                    logging.getLogger("veyra.execution").exception(
                        "execution_cycle_traceback"
                    )
                if once:
                    return
                time.sleep(delay)
        except KeyboardInterrupt:
            self.stdout.write("Veyra execution layer stopping cleanly.")
        finally:
            release_controller(instance_id)
