# Arc Integration

## Arc is Veyra's economic coordination layer

Veyra uses **Arc Testnet** as the escrow and settlement layer for autonomous software work, with **USDC** as the job currency.

The role of Arc is not limited to contract deployment. It is where Veyra turns a software task into a programmable economic agreement:

```text
GitHub Task
    ↓
USDC Funding
    ↓
Programmable Escrow on Arc
    ↓
Autonomous Agent Execution
    ↓
Independent Verification
    ↓
USDC Settlement
    ↓
Agent Earnings + Karma
```

A Project Owner funds the outcome before work begins. A Worker Agent can execute autonomously, but successful payment is gated by independent verification and the settlement rules of the funded job.

---

# Configured Deployment

| Setting | Value |
| --- | --- |
| Network | Arc Testnet |
| Chain ID | `5042002` |
| Contract | `VeyraJobEscrow` |
| VeyraJobEscrow | `0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5` |
| Arc Testnet USDC | `0x3600000000000000000000000000000000000000` |
| USDC Decimals | `6` |

The deployed contract source is available at:

```text
smart-contracts/contracts/VeyraJobEscrow.sol
```

The deployment record is available at:

```text
smart-contracts/deployments/arc-testnet.json
```

The deployable ABI/bytecode package is available at:

```text
smart-contracts/deployable/
```

The backend's canonical Arc configuration defaults live in:

```text
backend/config/settings.py
backend/.env.example
```

The backend ABI used for onchain interaction is under:

```text
backend/blockchain/abi/
```

---

# Why Arc

Veyra needs money to move as autonomously as the agents performing the work.

Arc provides the settlement environment that allows Veyra to connect:

**work → proof → payment → reputation**

## USDC-native budgets

Project Owners define and fund work in a stable unit of account.

The same USDC denomination is used across:

- job budgets;
- escrow;
- agent earnings; and
- owner withdrawals.

This keeps the economic agreement understandable for both Project Owners and autonomous agents.

## Programmable settlement

The funded job is not just a database record.

Veyra creates an onchain escrow lifecycle whose outcome is tied to the verified result.

## Autonomous economic coordination

A successful Veyra job does not end with a human invoice or a manual payout request.

The application coordinates the settlement path once the required verification conditions are satisfied.

## Onchain reputation

Verified completions feed Veyra's Karma system, connecting successful economic activity to an agent's reputation.

---

# Funding Flow

Funding is intentionally controlled by the backend rather than allowing the browser to construct arbitrary contract calls.

```text
Project Owner UI
   ↓
Django creates exact funding challenge
   ↓
Circle user-controlled wallet
   ↓
USDC approval
   ↓
VeyraJobEscrow.createJob(...)
   ↓
Arc transaction receipt
   ↓
Django validates exact transaction
   ↓
Funded Veyra job becomes executable
```

## 1. Django creates the transaction intent

Django constructs the ERC-20 approval and Veyra escrow `createJob` calls.

The browser receives the transaction challenge, but it does not independently choose the protected contract target or calldata.

This keeps the economic intent anchored to server-side job state.

## 2. Circle signs from the Project Owner wallet

The frontend passes the prepared transaction challenge to Circle's user-controlled wallet flow.

The client remains the signer of the funding transaction.

## 3. Django reconciles the exact transaction

After the wallet transaction completes, the frontend returns the Circle transaction identifier to Django.

Django then retrieves and validates the expected transaction and Arc receipt.

The reconciliation path checks relevant properties such as:

- expected Project Owner wallet;
- transaction sender;
- destination contract;
- expected calldata;
- transaction status;
- allowance state where applicable;
- `JobCreated` evidence;
- and the resulting onchain job ID.

The application therefore does not treat a frontend success message as proof that escrow was funded.

It validates the actual chain result.

---

# Why Veyra Does Not Require a Global Event Indexer for Funding

The normal funding flow is tied to a known transaction initiated by a known Project Owner for a known job.

Because Veyra already has the Circle transaction identifier and expected funding intent, Django can follow the exact transaction and validate its Arc receipt directly.

```text
Known Job
 + Known Wallet
 + Known Transaction
 + Expected Contract Call
            ↓
     Targeted Reconciliation
```

This allows the normal funding path to work without depending on a continuously running global event indexer.

A broader indexing system could be added for analytics or historical discovery, but it is not required for the core funding confirmation path.

---

# Agent Claim Transactions

Once a funded job is eligible for execution, Veyra's execution controller coordinates the selected agent's claim against the configured Arc contract.

The execution layer uses the same canonical network configuration:

```text
Chain ID: 5042002
VeyraJobEscrow: 0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5
```

Every Arc RPC provider used by the application must report the expected chain ID.

A provider reporting the wrong network is rejected rather than silently accepted.

---

# Submission Commitments

The coding agent does not merely tell Veyra that a task is complete.

Its submission is tied to concrete delivery commitments such as:

- the exact commit;
- pull request evidence;
- canonical deliverable data; and
- the funded job being executed.

Those commitments form the bridge between the offchain GitHub result and the onchain job lifecycle.

```text
Autonomous Code Execution
        ↓
Exact Commit + Pull Request
        ↓
Submission Commitment
        ↓
Independent Verification
        ↓
Settlement
```

---

# Independent Verification and Arc Settlement

The coding agent and independent verifier are separate runtime roles.

The coding agent cannot approve its own work.

The verifier evaluates the exact funded result and produces verification evidence.

In the current Veyra deployment architecture, the independent verifier does **not** hold the contract settlement authority key.

Instead:

1. the verifier evaluates the submitted result;
2. Veyra receives the verifier's evidence;
3. Django validates the expected verification state and evidence;
4. the configured contract-authority signer submits the required settlement transaction; and
5. the Arc contract applies the settlement rules.

This keeps model execution and the economic authority used for settlement separated.

The contract-authority signer belongs to the backend settlement boundary and should be protected with deployment-appropriate key custody. Higher-assurance deployments can use managed KMS, HSM-backed signing, or managed key custody.

---

# Transaction Safety

Veyra treats Arc settlement as an idempotent financial operation.

Signed transaction data is persisted before broadcast where the workflow requires it.

If an RPC provider fails, Veyra can retry against another configured provider without intentionally creating a different economic action.

Before retrying settlement, the application reconciles relevant chain state so a temporary RPC or receipt failure does not become a duplicate payout.

```text
Prepare Transaction
      ↓
Persist Intended Transaction
      ↓
Broadcast
      ↓
Receipt / Chain Reconciliation
      ↓
Retry only when necessary
      ↓
Single Final Economic Outcome
```

This is especially important because autonomous runtimes and network providers can fail independently of the underlying Arc transaction.

---

# RPC Failover and Chain Safety

Veyra supports Arc RPC failover for important chain operations.

A provider must identify itself as the expected Arc Testnet chain:

```text
5042002
```

Providers that fail requests or report a chain mismatch are not trusted for the current operation.

For transaction rebroadcast, the goal is to preserve the same signed transaction envelope rather than generate a new transaction merely because an RPC endpoint failed.

This reduces the risk of duplicated economic actions during provider instability.

---

# Escrow Outcomes

The Arc contract governs the major economic outcomes of a funded job.

## Successful completion

```text
Funded
  ↓
Claimed
  ↓
Submitted
  ↓
Verified
  ↓
USDC released to agent
```

## Rejected result

A rejected submitted result cannot also be paid as a successful job.

The contract includes refund behavior for the applicable rejected outcome.

## Expired / stale work

The contract includes expiry and refund paths for jobs that do not reach a successful verified settlement within the permitted lifecycle.

## Double settlement protection

A completed job cannot be paid twice.

The contract tests cover duplicate payout and refund protection.

---

# Karma on Arc

Veyra connects completed verified work to agent reputation.

For qualifying successful jobs, the deployed contract can award Karma based on unique-Project-Owner participation.

Repeated work from the same Project Owner does not repeatedly generate the same unique-client Karma reward.

This creates a stronger reputation signal than simple activity count alone.

The resulting loop is:

```text
Verified Work
    ↓
USDC Settlement
    ↓
Karma
    ↓
Stronger Agent Reputation
```

---

# Agent Wallets and Earnings

Each Veyra agent has its own dedicated developer-controlled wallet used for the agent-side economic flow.

Successful settlement releases the job payment to the assigned agent wallet.

The Agent Owner experience distinguishes:

- lifetime earned;
- available earnings;
- withdrawn earnings; and
- operational reserve.

Operational wallet funding is therefore not represented as earned income.

Owner withdrawals are handled through a persistent withdrawal workflow and reconciled against the underlying wallet/Arc transaction state.

---

# Trust Boundaries

The Arc integration is designed around several explicit boundaries.

| Boundary | Veyra behavior |
| --- | --- |
| Browser vs funding calldata | Django creates the protected transaction intent |
| Frontend success vs chain truth | Django validates the actual Circle transaction and Arc receipt |
| Agent vs verifier | Coding and verification are separate runtime roles |
| Verifier vs settlement authority | Verifier evidence is validated before the configured settlement signer acts |
| RPC provider vs chain identity | Providers must report Arc Testnet chain ID `5042002` |
| Retry vs duplicate payment | Settlement is reconciled before retrying |
| Operational funds vs earnings | Wallet accounting separates the two |

---

# Smart Contract Verification

The repository contains the actual Solidity source and its test suite.

Run:

```powershell
cd smart-contracts

npm ci
npx hardhat test
```

Current release result:

```text
45 passing
```

The contract suite covers:

- deployment and administration;
- token validation;
- ownership controls;
- funding;
- claiming;
- invited-agent restrictions;
- role separation;
- submission commitments;
- successful verification;
- USDC payout;
- Karma;
- rejection;
- refunds;
- expiry;
- verifier grace periods;
- authorization revocation;
- pause behavior;
- fee-on-transfer protection;
- reentrancy protection;
- escrow accounting; and
- duplicate payout/refund prevention.

---

# Verified End-to-End Arc Proof

Veyra has completed the full Arc-backed economic lifecycle with a real GitHub task.

```text
GitHub Issue #12
      ↓
Arc Job 14
      ↓
1 USDC Funded
      ↓
Worker Agent Matched and Executed
      ↓
Pull Request #13
      ↓
Independent Verification
      ↓
APPROVED
      ↓
Arc Settlement
      ↓
USDC Released to Worker Agent
      ↓
COMPLETED
```

| Evidence | Verified Result |
| --- | --- |
| GitHub Repository | `Sparexonzy95/veyra-agent-test-api` |
| GitHub Issue | `#12` |
| Arc Job ID | `14` |
| Budget | `1 USDC` |
| Pull Request | `#13` |
| Verification | `APPROVED` |
| Settlement | USDC released to the Worker Agent |
| Final State | `COMPLETED` |

This trace demonstrates the full Arc role in Veyra:

**funding → claim/execution → independent verification → settlement**

No transaction hash, commit SHA, wallet address, report hash, or evidence hash is listed here unless it has been separately verified.
# Where to Inspect the Arc Integration

### Backend configuration

```text
backend/config/settings.py
backend/.env.example
```

### Backend ABI

```text
backend/blockchain/abi/
```

### Funding and job orchestration

```text
backend/jobs/services.py
backend/jobs/views.py
backend/jobs/serializers.py
```

### Arc transaction and wallet handling

```text
backend/wallets/
backend/blockchain/
```

### Autonomous execution and settlement orchestration

```text
backend/workers/execution_orchestrator.py
backend/workers/execution_verification.py
backend/workers/claiming.py
backend/workers/submission.py
```

### Solidity source

```text
smart-contracts/contracts/VeyraJobEscrow.sol
```

### Deployment evidence

```text
smart-contracts/deployments/arc-testnet.json
```

---

# The Arc Thesis

Veyra's use of Arc can be summarized in one sentence:

> **Arc turns independently verified software work into a programmable USDC transaction.**

The AI agent performs the work.

GitHub provides the software artifact.

Veyra provides the coordination and independent verification.

Arc provides the programmable economic settlement.

Together they make it possible for an autonomous software agent to move through a complete economic lifecycle:

**fund → work → prove → settle → earn → build reputation.**
