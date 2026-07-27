# VeyraJobEscrow v0.4.0 — Internal Security Review

**Scope:** `contracts/VeyraJobEscrow.sol`, token-call library, mocks, deployment scripts, and tests.  
**Network target:** Arc Testnet.  
**Review type:** Internal manual review plus adversarial Hardhat tests.  
**Not:** an independent professional audit or a guarantee of security.

## Executive result

No unresolved critical or high-severity code defect was identified in the reviewed v0.4.0 source. Seven confirmed design/security weaknesses from v0.3.0 were fixed. Forty-five tests pass after a clean compile.

## Fixed findings

### F-01 — Worker could also be the verifier

**Previous severity:** High  
**Problem:** A wallet authorised in both lists could claim an open job and approve its own work. A client could also select itself as verifier.  
**Fix:** Enforce per-job separation:

- verifier cannot equal client,
- verifier cannot equal invited provider,
- verifier cannot claim an open job.

Deployment also refuses identical default agent/verifier addresses.

### F-02 — Early submissions could lock funds until the far-away job expiry

**Previous severity:** Medium  
**Problem:** The verification grace period was calculated from `expiresAt`. A job submitted on day one of a 90-day task could remain locked for roughly 90 days if the verifier disappeared.  
**Fix:** Verification deadline is now `submittedAt + verificationGracePeriod`.

### F-03 — Claim-and-disappear griefing

**Previous severity:** Medium  
**Problem:** An authorised agent could claim a public job and do nothing, blocking every other agent until final expiry.  
**Fix:** Every claim gets a bounded `claimDeadline`. After it passes, the client can call `refundAbandonedClaim()` and recover the full escrow.

### F-04 — Revoked verifier could still settle old jobs

**Previous severity:** Medium  
**Problem:** Verifier authorisation was checked only at job creation. Revoking a compromised key did not stop it from paying or rejecting existing jobs.  
**Fix:** `verifyAndPay()` and `rejectAndRefund()` now require current verifier authorisation.

### F-05 — Revoked agent could still submit

**Previous severity:** Low/Medium  
**Problem:** Agent authorisation was checked at claim time but not at submission.  
**Fix:** `submitWork()` requires current agent authorisation. If revoked, the client can recover after the claim deadline.

### F-06 — Trivial repeat-client Karma farming

**Previous severity:** Low  
**Problem:** The same client/provider pair could recycle USDC through repeated jobs and receive 100 Karma each time.  
**Fix:** Qualifying Karma is awarded once per unique client address. Every successful job still increments `completedJobs` and `totalEarned`.

**Residual:** Multiple fake client wallets can still farm reputation. Karma is therefore explicitly informational and never grants settlement power.

### F-07 — Evidence commitment was not domain-bound

**Previous severity:** Low  
**Problem:** A raw report hash could be reused without cryptographically binding it to the exact job, deliverable, verdict, and reason.  
**Fix:** Store a domain-separated evidence commitment covering chain ID, contract, job ID, deliverable, report, verdict, and rejection reason.

### F-08 — Cross-function token reentrancy surface

**Previous severity:** Medium  
**Problem:** `claimJob()` and `submitWork()` were not guarded, so a malicious payment token callback could mutate a second job during a guarded token transfer.  
**Fix:** All job-mutating entry points are now protected by the same reentrancy guard. A malicious-token payout test confirms cross-function callbacks fail.

### F-09 — Deployment could silently use the wrong token or same role wallet

**Previous severity:** Medium operational risk  
**Problem:** Environment values could point to a different token, or use one address for both worker and verifier.  
**Fix:** The Arc deploy script now:

- requires chain ID `5042002`,
- requires `0x3600000000000000000000000000000000000000`,
- checks token bytecode,
- rejects zero/invalid addresses,
- rejects identical agent and verifier addresses.

## Verified security invariants

- `totalEscrowed` is reduced before every outbound settlement and all changes revert on token-transfer failure.
- Owner recovery of payment tokens is limited to `balance - totalEscrowed`.
- Rejected, completed, cancelled, abandoned, and expired jobs cannot be paid or refunded twice.
- Fee-on-transfer deposits revert rather than creating undercollateralised jobs.
- Delivery commitments include chain ID, contract address, job ID, repository, task, policy, commit, and PR.
- At exact deadline boundaries, the active party retains priority; refund opens only after the deadline.
- Pausing cannot trap clients permanently because cancellation and refund paths remain callable.

## Residual risks and trust assumptions

### R-01 — Verifier trust

The contract enforces the assigned verifier's decision; it does not execute tests. A compromised verifier can approve bad work or reject good work. This is the largest remaining system risk.

**Mitigation:** isolated deterministic verification, strict wallet policy, key rotation, event monitoring, and later threshold/multi-verifier approval.

### R-02 — Owner/admin trust

The owner controls global agent/verifier authorisation and pause. The owner cannot withdraw active escrow, but can cause denial of service by pausing or revoking roles.

**Mitigation:** use a dedicated multisig or tightly controlled Circle wallet in production. Monitor every admin event.

### R-03 — Karma remains Sybil-gameable

Unique-client scoring blocks simple repetition but not many fake client wallets.

**Mitigation:** keep Karma informational. Later weight it using verified GitHub identity, economic volume, time, unique counterparties, and/or ERC-8004 history.

### R-04 — External USDC behaviour

Blacklisting, token pausing, or an upstream token failure can make payment/refund transfers fail. Because transfers revert atomically, accounting remains intact, but funds may stay locked until the token becomes transferable.

### R-05 — No dispute or appeal layer

A rejection refunds the client immediately. This is intentional for deterministic MVP tasks but gives the agent no appeal route.

### R-06 — Offchain commitment correctness

Repository, task, policy, commit, PR, and report hashes are only useful if the backend computes and stores them consistently. The backend must use canonical encodings and preserve the referenced artifacts.

### R-07 — Public-claim competition

Open jobs are first-come-first-served among authorised agents. Mempool competition/front-running is possible. Use `invitedProvider` for targeted assignments.

### R-08 — Lost client key

Only the client can cancel or claim refunds. A lost client key can strand that client's escrow. Adding an admin rescue would increase custody risk, so it is intentionally absent.

## Testing

- Clean Solidity compile with pinned `solc 0.8.24`
- 45 passing Hardhat tests
- Reentrancy tests for job creation and payout cross-calls
- Role-separation and revocation tests
- Exact funding and fee-on-transfer tests
- Completion/rejection/refund double-spend tests
- Stale claim and early-submission liveness tests
- Karma unique-client tests
- Evidence domain-binding tests
- Dependency audit: 0 known npm vulnerabilities in the locked package set

## Deployment recommendation

Suitable for controlled Arc Testnet use after manual review of environment addresses. Not recommended for real-value mainnet deployment until an independent auditor reviews the final code and the verifier backend is threat-modelled separately.
