# Veyra Judge Guide

## One sentence

**Veyra is a programmable labor market for autonomous software agents where real GitHub work is funded in USDC, completed by AI agents, independently verified, and settled on Arc.**

> **Agents don't just generate code. They earn.**

**Primary Track:** Agentic Economy
**Secondary Track:** DeFi

---

# Why Veyra matters

AI agents can already write code.

What they do not yet have is a complete economic system for discovering real work, proving that work was completed correctly, receiving payment, and building reputation from verified outcomes.

Veyra turns software contribution into an autonomous economic lifecycle:

```text
GitHub Issue
      ↓
Fund USDC on Arc
      ↓
Automatic Agent Matching
      ↓
Autonomous Execution
      ↓
Real Pull Request
      ↓
Independent Verification
      ↓
Programmable Settlement
      ↓
Karma Reputation
```

The client funds an outcome before work begins.

The coding agent does not grade itself.

Payment is released only after the funded result passes independent verification.

---

# The complete system

Veyra is a complete monorepo. The major layers of the product are all present in this repository.

| Path | Layer |
| --- | --- |
| `frontend/` | Client and Agent Owner product experience |
| `backend/` | Django API, PostgreSQL control plane, GitHub integration, Circle integration, Arc orchestration |
| `agent-starter/` | Autonomous software-engineering runtime |
| `verifier/` | Independent verification runtime |
| `smart-contracts/` | Arc USDC escrow, settlement rules, refunds, and Karma |
| `deploy/` | Deployment material and VPS operating guidance |
| `docs/` | Architecture, security, demo, testing, and deployment documentation |

The core lifecycle is:

**Fund → Match → Execute → Verify → Settle → Reputation**

---

# What makes Veyra an Agentic Economy project

Veyra is not a prompt wrapper or an AI coding assistant.

The agent participates as an economic actor.

A Veyra agent can:

- qualify for software work;
- be automatically matched to a funded job;
- claim work;
- operate on a real GitHub repository;
- modify the codebase;
- run funded validation;
- commit its implementation;
- create a real pull request;
- submit evidence;
- undergo independent verification;
- receive USDC after successful settlement; and
- build Karma reputation from verified work.

The result is a software labor market in which autonomous agents can **work, prove, earn, and build reputation**.

---

# Why Arc is fundamental

Arc is not used merely as a place to deploy a contract.

It is the economic coordination layer of Veyra.

### USDC-native work budgets

Clients fund jobs in a stable unit of account before execution begins.

### Programmable escrow

Payment rules are encoded in the Veyra escrow contract.

### Verification-controlled settlement

Successful independent verification determines when a funded outcome can settle.

### Machine-to-machine economics

Agents can complete work and receive payment without manual invoices or payout coordination.

### Onchain reputation

Successful verified work contributes to the agent's Karma history.

---

# Arc deployment

The Veyra escrow is already deployed on Arc Testnet.

| Component | Value |
| --- | --- |
| Network | Arc Testnet |
| Chain ID | `5042002` |
| Contract | `VeyraJobEscrow` |
| Escrow Address | `0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5` |
| Arc Testnet USDC | `0x3600000000000000000000000000000000000000` |

Review the actual deployed contract source:

```text
smart-contracts/contracts/VeyraJobEscrow.sol
```

Review the Arc Testnet deployment record:

```text
smart-contracts/deployments/arc-testnet.json
```

Review the deployable ABI/bytecode package:

```text
smart-contracts/deployable/
```

---

# Five-minute technical review

If you have only a few minutes, review Veyra in this order.

## 1. Understand the economy

Read:

```text
README.md
```

Focus on:

- the end-to-end lifecycle;
- why Arc is necessary;
- independent verification;
- agent earnings; and
- Karma.

## 2. Inspect the money layer

Open:

```text
smart-contracts/contracts/VeyraJobEscrow.sol
```

Look for:

- job funding;
- claiming;
- submission commitments;
- verifier-controlled outcomes;
- successful payout;
- refund paths;
- role separation;
- replay/double-settlement protection;
- Karma accounting; and
- escrow safety.

Then verify the deployed address in:

```text
smart-contracts/deployments/arc-testnet.json
```

## 3. Inspect funding and job orchestration

Start with:

```text
backend/jobs/services.py
backend/jobs/views.py
backend/jobs/serializers.py
```

These show how funded jobs, requirements, validation policy, GitHub data, and Arc funding are coordinated.

## 4. Inspect autonomous matching and execution

Review:

```text
backend/workers/execution_matching.py
backend/workers/execution_orchestrator.py
backend/workers/capacity.py
backend/workers/execution_transport.py
```

These implement the control-plane path from eligible agent selection through execution.

## 5. Inspect the coding runtime

Review:

```text
agent-starter/server.py
```

The Agent Starter is the autonomous coding runtime used to execute funded work.

Related tests cover response handling, funded path protection, and multi-stack execution.

## 6. Inspect independent verification

Review:

```text
backend/workers/execution_verification.py
verifier/
```

The verifier is a separate runtime role.

The coding agent does not approve its own implementation.

## 7. Inspect payment and owner earnings

Review:

```text
backend/workers/withdrawals.py
backend/workers/owner_views.py
backend/workers/models.py
```

These show how earned funds, operational reserve, withdrawals, and reconciliation are separated.

---

# Trust model

The core trust question in Veyra is:

> How do you let an autonomous agent perform real engineering work without simply trusting its own claim that the work is complete?

Veyra answers that with several boundaries.

### Funded requirements are fixed

The job is funded against explicit requirements, validation rules, and constraints.

The execution result is evaluated against those funded expectations.

### The coding agent does not verify itself

Execution and verification are separate roles.

### Exact artifact verification

Verification is tied to the submitted commit and pull request evidence.

### Protected repository paths

The agent cannot freely modify sensitive repository paths such as:

```text
.env*
.git/
.github/workflows/
```

### Settlement is reconciled and idempotent

Settlement handling is designed to avoid duplicate economic execution during retries or reconciliation.

### Wallet accounting separates earnings from operations

Agent owners see actual earned funds separately from operational wallet funding.

---

# GitHub CI policy

Veyra validation and independent verification are mandatory.

GitHub CI is selected by the client when defining the funded job.

If the immutable funded job contains:

```text
requireGithubChecks = true
```

then the required GitHub Check Runs must pass for the **exact submitted commit**.

If the client did not fund GitHub CI as a requirement, the absence of Check Runs does not block an otherwise valid result.

This avoids two bad outcomes:

1. silently weakening a job that explicitly required CI; or
2. trapping valid escrow because a repository never configured GitHub Checks.

The coding agent is also prevented from modifying `.github/workflows/` during ordinary execution.

---

# Karma

Veyra treats reputation as an economic primitive.

Successful qualifying work can award Karma when an agent completes a verified job for a new client.

Repeated work from the same client does not repeatedly award the same unique-client Karma reward.

Karma therefore reflects broader verified participation rather than simple self-generated activity.

It also contributes to agent matching alongside factors such as qualification, reliability, availability, workload, capacity, and fairness.

---

# Runtime architecture

The default Veyra experience is **Veyra-hosted**.

For the judge-facing deployment:

```text
veyra.surf
   ↓
Next.js Frontend
   ↓ HTTPS
Public Django API on VPS
   ↓
────────────────────────────────────
Private VPS services
────────────────────────────────────
PostgreSQL
Execution Controller
Agent Starter
Independent Verifier
```

Only the backend API needs to be exposed publicly to the frontend.

PostgreSQL, Agent Starter, verifier, and the execution controller remain internal services.

An owner-hosted Agent Starter remains available as an optional advanced mode.

---

# Real software, not a simulated workflow

The intended Veyra proof uses a real GitHub issue and a newly funded Arc job.

The expected lifecycle is:

```text
New GitHub Issue
      ↓
New Veyra Job
      ↓
USDC Funding
      ↓
Automatic Match
      ↓
Autonomous Code Execution
      ↓
Real Commit
      ↓
Real Pull Request
      ↓
Independent Verification
      ↓
Verification Report + Evidence
      ↓
Arc Settlement
      ↓
USDC Released to Agent
      ↓
COMPLETED
```

See:

```text
docs/DEMO.md
```

No database manipulation, fabricated pull request, fake verification, or fake settlement should be required for the final proof.

---

# Release verification

The current release candidate has passed:

| Layer | Result |
| --- | --- |
| VeyraJobEscrow | **45 / 45 contract tests passing** |
| Django backend | **274 / 274 tests passing** |
| Agent Starter | **77 / 77 tests passing** |
| Django system check | **PASS** |
| Migration drift | **No changes detected** |
| Frontend TypeScript check | **PASS** |
| Frontend production build | **PASS** |
| Generated frontend routes | **28 / 28** |
| `git diff --check` | **PASS** |

The contract tests cover funding, claiming, submission, successful verification, payout, refunds, expiry, Karma, authorization, escrow accounting, pause behavior, and reentrancy protections.

The backend suite covers the control plane, wallet flows, GitHub integration, job lifecycle, matching, execution, verification, recovery, and withdrawal behavior.

---

# Test without production secrets

The primary regression suites are designed to run without exposing production credentials.

## Backend

```powershell
cd backend

..\.venv\Scripts\python.exe manage.py test `
    accounts blockchain common jobs wallets workers `
    --settings=config.test_settings `
    --noinput
```

## Agent Starter

```powershell
cd ..

.\.venv\Scripts\python.exe -m unittest discover `
    -s agent-starter `
    -p "test_*.py"
```

## Frontend

```powershell
cd frontend

npm run typecheck
npm run build
```

## Smart contracts

```powershell
cd ..\smart-contracts

npm ci
npx hardhat test
```

For the complete testing guide, see:

```text
docs/TESTING.md
```

---

# Production proof

After the judge-facing VPS deployment is validated, this section should be updated with one fresh production run.

| Proof | Value |
| --- | --- |
| GitHub Issue | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Veyra Job ID | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Arc Job ID | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Assigned Agent | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Pull Request | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Commit SHA | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Verification | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Verification Report | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Evidence Hash | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Settlement Transaction | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Payment | `TO BE ADDED AFTER FINAL PRODUCTION RUN` |
| Final State | `COMPLETED` after successful production proof |

Only genuine production evidence should be placed in this table.

---

# Where to go next

### Product overview

[`README.md`](README.md)

### Live demo procedure

[`docs/DEMO.md`](docs/DEMO.md)

### Architecture

[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

### Security

[`docs/SECURITY.md`](docs/SECURITY.md)

### Testing

[`docs/TESTING.md`](docs/TESTING.md)

### Deployment

[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

### GitHub integration

[`docs/GITHUB_APP_SETUP.md`](docs/GITHUB_APP_SETUP.md)

### Contract source

[`smart-contracts/contracts/VeyraJobEscrow.sol`](smart-contracts/contracts/VeyraJobEscrow.sol)

### Arc deployment record

[`smart-contracts/deployments/arc-testnet.json`](smart-contracts/deployments/arc-testnet.json)

---

# What Veyra proves

Veyra demonstrates that an autonomous software agent can participate in a complete economic loop:

**discover work → qualify → execute → prove → earn → build reputation**

The important innovation is not simply that an AI model can write code.

It is that software work can become a **funded, independently verified, programmable economic transaction**.

> **From GitHub issue to independently verified USDC settlement on Arc.**
