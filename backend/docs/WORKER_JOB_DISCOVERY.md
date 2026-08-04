# Veyra Worker Job Discovery — Phase 3 Step 1

This phase adds read-only autonomous discovery and queueing for Veyra's ACTIVE
coding worker. It does not claim jobs, move USDC, clone repositories, or invoke
OpenCode.

## Safety boundary

The discovery service only stores public repository metadata, public Arc state,
and deterministic eligibility results. It does not store or pass:

- Circle API keys or entity secrets
- Circle recovery files
- GitHub tokens
- OpenCode provider credentials
- private keys

## Discovery sources

1. `JobCreated` fast path: after the Arc indexer projects a funded job, an
   `on_commit` callback attempts to queue it immediately.
2. Periodic reconciliation: `discover_worker_jobs` re-checks all locally
   projected OPEN jobs against authoritative Arc state.

Both paths are idempotent through the unique `(worker, job)` queue constraint.
The reconciliation path is the authoritative fallback if the fast path fails.

## Eligibility gate

A job is queued only when all checks pass:

- worker is ACTIVE and discovery is explicitly enabled
- controlled GitHub test has passed
- worker and verifier are authorised onchain
- escrow is not paused
- Arc reports the job as FUNDED and unclaimed
- the job is open to all agents or invited to this worker wallet
- Arc commitments match the locked Django funding snapshot
- repository host is GitHub
- delivery type is PULL_REQUEST
- budget meets the worker minimum
- enough time remains before expiry
- repository stack matches at least one worker skill when stack metadata exists
- worker capacity is available

## Queue states introduced

- DISCOVERED
- QUEUED
- DEFERRED
- INELIGIBLE
- STALE
- CLAIM_PENDING
- CLAIMED
- EXECUTING
- SUBMISSION_PENDING
- SUBMITTED
- COMPLETED
- FAILED

Phase 3 Step 1 writes only the first five states. Later phases will own claim,
execution, submission, and settlement transitions.

## Commands

```powershell
python manage.py enable_worker_discovery
python manage.py discover_worker_jobs
python manage.py show_worker_job_queue
python manage.py disable_worker_discovery
```

`enable_worker_discovery` performs live read-only Arc checks before changing the
flag.

`discover_worker_jobs` never sends a blockchain transaction and never changes a
GitHub repository.

`disable_worker_discovery` is the emergency stop for finding and queueing new
jobs. It does not alter jobs already claimed onchain.

## Environment settings

```ini
WORKER_DISCOVERY_MIN_REMAINING_SECONDS=900
WORKER_DISCOVERY_REQUIRE_SKILL_MATCH=true
```

## Next phase

Phase 3 Step 2 consumes one `QUEUED` item, performs a final GitHub/Arc preflight,
and submits `claimJob(jobId)` through the worker's Circle developer-controlled
wallet using idempotent transaction tracking.
