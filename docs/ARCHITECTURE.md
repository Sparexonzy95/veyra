# Architecture

## Components

`frontend` is a Next.js application deployed independently to Vercel. It talks
to Django over credentialed HTTPS and uses Circle's browser SDK only for the
user-controlled wallet challenge returned by the backend.

`backend` is the system of record. Django/PostgreSQL stores users, job drafts,
wallet transaction records, on-chain jobs, agents, qualifications, leases,
execution evidence, and verifier assignments. A separate execution-controller
process advances recoverable workflow stages.

`agent-starter` is an owner-operated runtime. It keeps the owner's model key and
Ed25519 private key, polls the authenticated runtime API, performs work in an
isolated temporary workspace, and returns signed evidence.

`verifier` reuses that runtime engine in a restricted verifier role with a
separate identity. It evaluates an agent submission with read-only repository
access and returns signed findings to Django.

The VeyraJobEscrow contract on Arc is the economic state machine. Circle
user-controlled wallets authorize client approval/funding transactions. The
backend's narrowly scoped server signer performs contract-owner operations that
the current testnet contract requires.

## Job lifecycle

1. A client authenticates, connects a GitHub App installation, and drafts a
   repository/issue-scoped job.
2. Django constructs USDC approval and escrow funding calldata. Circle presents
   the wallet challenge to the client.
3. Django records the Circle transaction ID and validates its exact Arc receipt.
4. The execution controller discovers the funded on-chain job, filters/ranks
   eligible connected agents, and reserves an assignment.
5. The selected runtime accepts a lease, receives short-lived job credentials,
   executes and tests the task, and returns signed commit/PR evidence.
6. Django assigns an independent verifier, which reviews with read-only access
   and submits a signed decision.
7. Django validates both results and sends the contract-authorized settlement.
   Arc releases funds according to the escrow outcome.

## Trust boundaries

- The browser is untrusted for contract targets and calldata.
- Agent owners control their runtimes and model accounts; signed responses and
  scoped credentials limit what the control plane accepts.
- Worker output is not sufficient for payout; verification is separate.
- PostgreSQL coordinates leases and retry state so duplicate controllers do not
  independently advance the same assignment.
- Arc is authoritative for escrow and settlement, while Django is authoritative
  for off-chain orchestration and evidence.

Legacy `RunnerDevice`-named database structures remain because the hosted
runtime implementation depends on their migration history. The standalone
Runner client and its production URL surface are not part of the supported
architecture.
