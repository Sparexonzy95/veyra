# Locked Client Actor Flow

## User-visible flow

```text
Continue with Google or Email
→ Choose Post Jobs
→ Wallet prepared automatically
→ Dashboard
→ Create Job
→ Review
→ Fund Job
→ Open
→ Agent Working
→ Under Review
→ Completed or Refunded
```

The frontend has six primary surfaces:

1. Login
2. Actor selection
3. Dashboard
4. Create Job modal
5. Review and funding
6. Job detail

## Django-owned logic

Django owns:

- provisional Circle authentication exchange;
- Veyra HTTP-only application sessions;
- wallet-bound user identity;
- CLIENT capability;
- Circle Arc SCA wallet initialization and sync;
- GitHub issue preview;
- job drafts and immutable funding snapshots;
- canonical repository, task, and policy commitments;
- exact USDC approval calldata;
- `createJob` calldata;
- Circle challenge records;
- Arc event indexing;
- dashboard projections;
- contextual cancellation/refund selection.

## Funding flow

```text
Review Job
→ Django locks the funding snapshot
→ Django checks exact USDC allowance
→ Circle approval challenge when needed
→ Arc confirms approval
→ Django creates createJob challenge
→ user approves in Circle Web SDK
→ Arc emits JobCreated
→ Django indexer marks job OPEN
```

A successful Circle challenge is not enough to mark the job funded.

## Allocation flow

```text
Job becomes OPEN
→ authorised worker agents inspect it
→ suitable agent runs read-only preflight
→ agent chooses ACCEPT or SKIP
→ accepted agent calls claimJob
→ Arc emits JobClaimed
→ client sees AGENT WORKING
```

Allocation is not part of the client backend beyond publishing confirmed open jobs.

## Contextual client actions

The frontend asks one endpoint for an action challenge. Django reads Arc and selects:

- `cancelUnclaimedJob` for an open, unclaimed job;
- `refundAbandonedClaim` after the worker claim deadline;
- `claimExpiredRefund` after an open-job expiry or verifier timeout.

The user only sees **Cancel Job** or **Claim Refund**.
