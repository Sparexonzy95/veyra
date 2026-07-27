# Veyra Worker Activation — Phase 2 Step 1

This patch synchronizes the worker wallet's on-chain authorization from the
deployed Veyra escrow contract and runs a complete live readiness gate before
the controlled test assignment.

## What the patch checks

- Worker profile and skills
- Stored OpenCode connection
- Live OpenCode health check
- Circle worker wallet metadata
- Payout wallet
- Stored GitHub connection
- Live GitHub token/account verification
- Arc Testnet chain ID
- Escrow contract pause state
- Worker wallet authorization
- Verifier wallet authorization

## Safety behavior

- The synchronization command performs view calls only.
- No blockchain transaction is submitted.
- The worker is not marked ACTIVE.
- Job discovery stays disabled.
- Passing readiness moves the worker to TESTING.
- The test assignment remains incomplete until the next phase.

## Commands

```powershell
python manage.py sync_worker_authorisation
python manage.py check_worker_readiness
```

## Expected final state

```text
Status: TESTING
contract_authorised: True
test_assignment_passed: False
discovery_enabled: False
```
