# Veyra Custom Escrow Contract v0.4.0

Contract-only package for Veyra's Arc Testnet job escrow.

## What the contract does

1. A client creates a software job and deposits USDC.
2. An authorised AI-agent wallet claims the job.
3. The agent submits a commit hash and pull-request number before its claim deadline.
4. The assigned independent verifier submits a report commitment.
5. `PASS` pays the agent; `FAIL` atomically refunds the client.
6. Unclaimed, abandoned, or verifier-stalled jobs have bounded refund paths.

Karma is informational only. It never controls job access or payment. A qualifying agent earns 100 Karma only once per unique client address, while every completed job is still counted.

## Security properties

- Client, worker, and verifier must be different addresses for the same job.
- Jobs are fully funded before they exist.
- Fee-on-transfer or underfunding tokens are rejected.
- Repository, task, policy, commit, PR, report, verdict, and rejection commitments are domain-separated.
- A claimed agent has a fixed claim-to-submission deadline.
- A submitted job has a verifier window measured from submission, not from the original job expiry.
- Revoked agents cannot submit; revoked verifiers cannot approve or reject.
- All token-moving and job-mutating functions are reentrancy protected.
- State changes roll back if a USDC transfer fails.
- Active escrow cannot be withdrawn by the owner.
- Emergency pause blocks new work and settlement but never blocks client cancellation/refund paths.

## Default Arc Testnet values

```env
ARC_TESTNET_RPC_URL=https://rpc.testnet.arc.network
ARC_USDC_ADDRESS=0x3600000000000000000000000000000000000000
VEYRA_VERIFICATION_GRACE_SECONDS=86400
VEYRA_CLAIM_SUBMISSION_SECONDS=43200
VEYRA_MIN_KARMA_USDC=1
```

The deployment script refuses non-Arc networks, refuses a different payment-token address, and refuses identical agent/verifier wallets.

## Install and test

Requires Node.js 22+.

```bash
npm ci
npm test
```

Expected result:

```text
45 passing
0 failing
```

## Deploy to Arc Testnet

1. Copy `.env.example` to `.env`.
2. Add a funded testnet deployer private key.
3. Put different public addresses in `VEYRA_AGENT_ADDRESS` and `VEYRA_VERIFIER_ADDRESS`.
4. Run:

```bash
npm run deploy:arc
```

Then copy the printed contract address into `VEYRA_ESCROW_ADDRESS` and run:

```bash
npm run check:deployment
```

## Files

- `contracts/VeyraJobEscrow.sol` — production contract
- `contracts/interfaces/` — minimal token interfaces
- `contracts/libraries/SafeERC20.sol` — checked token calls
- `contracts/mocks/` — test-only malicious and mock tokens
- `test/VeyraJobEscrow.test.cjs` — adversarial contract tests
- `scripts/` — Arc deployment and role setup
- `deployable/VeyraJobEscrow.json` — ABI and bytecode artifact
- `AUDIT_REPORT.md` — internal security review

## Important limitations

This is an internal review, not an independent professional audit. Keep it on testnet.

The contract cannot run GitHub tests. The verifier backend remains a trusted component that must:

- fetch the exact repository and commit,
- execute deterministic checks in an isolated environment,
- hash the immutable report,
- use the assigned verifier wallet only after the checks finish.

A malicious or compromised verifier can still approve bad work or reject good work. Production deployment should use stronger verifier controls, monitoring, and preferably multisig/threshold authorisation.
