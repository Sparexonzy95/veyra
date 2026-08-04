# Veyra Worker Arc Job Claim

Phase 3 Step 3 adds one typed, autonomous Arc claim operation for an already
queued worker job.

## Contract action

- Network: Arc Testnet
- Contract: configured `VEYRA_CONTRACT_ADDRESS`
- Function: `claimJob(uint256)`
- Sender: the worker's Circle developer-controlled ARC-TESTNET SCA wallet

The service never accepts arbitrary calldata. It constructs the claim request
from the immutable queue/job record and the configured escrow contract.

## Safety sequence

1. Run a read-only live preflight.
2. Lock the queue item and move it from `QUEUED` to `CLAIM_PENDING`.
3. Recheck Arc chain, pause state, agent authorization, verifier authorization,
   job commitments, expiry, capacity, and GitHub freshness.
4. Create one Circle developer-controlled contract-execution transaction using
   a stable queue-item idempotency key.
5. Persist the Circle transaction ID before polling.
6. Poll Circle to a terminal state.
7. Confirm the Arc receipt succeeded.
8. Decode the exact `JobClaimed` event.
9. Read `getJob(jobId)` and verify that the provider is the worker wallet.
10. Mark the queue item and local job projection `CLAIMED`.

## Crash and timeout behavior

A timeout or uncertain submission remains `CLAIM_PENDING`. The worker must use
`reconcile_worker_job_claim`; reconciliation never creates another Circle
transaction. It only reads Circle and Arc state.

## Commands

Read-only preflight:

```powershell
python manage.py preflight_worker_job_claim --job-id 5
```

Live claim:

```powershell
python manage.py claim_worker_job --job-id 5 --confirm-live-claim
```

Read-only reconciliation of a pending claim:

```powershell
python manage.py reconcile_worker_job_claim --job-id 5
```

## Secret boundaries

The database stores only public lifecycle metadata: an idempotency UUID, Circle
transaction ID/state, Arc transaction hash, block number, timestamps, and safe
failure text. It does not store Circle API keys, entity secrets, GitHub tokens,
OpenCode credentials, private keys, or recovery files.
