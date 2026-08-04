# Judge guide

Veyra turns autonomous software agents into economically accountable service
providers. The key idea is not merely AI code generation: payment is escrowed
in USDC on Arc before work, an owner-hosted agent signs and submits execution
evidence, an independent runtime verifies it, and settlement follows the
on-chain job state.

## Five-minute review

1. Read the flow and deployment values in `README.md`.
2. Inspect `backend/jobs/services.py` for USDC approval and escrow funding
   challenge creation.
3. Inspect `backend/wallets/transaction_sync.py` for exact transaction/receipt
   validation.
4. Inspect `backend/workers/execution_orchestrator.py` and
   `backend/workers/execution_verification.py` for assignment through
   verification and settlement.
5. Inspect `agent-starter/server.py` for the owner-hosted runtime boundary.
6. Run the commands in `docs/TESTING.md` or follow `docs/DEMO.md`.

## What to look for

- The browser never chooses protected contract calldata; Django creates it.
- Funding is reconciled against the exact stored Circle transaction and Arc
  receipt, including sender, target, and calldata.
- Runtime credentials are hashed server-side and execution results are signed.
- Agent workspaces are disposable and separate from provider secrets/identity.
- Worker and verifier roles are distinct; the verifier receives read-only
  repository access and cannot settle directly.
- The standalone Runner pairing client has been retired. The supported owner
  path is the one-time Agent Starter connection link.

## Chain configuration

- Arc Testnet chain ID: `5042002`
- Escrow contract: `0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5`
- Arc Testnet USDC: `0x3600000000000000000000000000000000000000`

These are source-controlled configuration defaults, not claims about a public
frontend/backend URL or a particular transaction.

## Test without secrets

The Django suite uses isolated settings and mocks external systems. The Agent
Starter unit tests likewise do not require a real model key. Frontend checking
requires only the locked npm dependencies. Exact commands and expected scope
are in `docs/TESTING.md`.
