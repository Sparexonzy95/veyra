# Veyra Demo Guide

## What the demo proves

The Veyra demo is designed to prove one thing clearly:

> **A real GitHub engineering task can be funded in USDC, completed by an autonomous AI agent, independently verified, and settled on Arc without simulating the core lifecycle.**

The judge-facing flow is:

```text
GitHub Issue
      ↓
Create Veyra Job
      ↓
Fund USDC on Arc
      ↓
Automatic Agent Matching
      ↓
Autonomous Engineering
      ↓
Real Commit + Pull Request
      ↓
Independent Verification
      ↓
Arc Settlement
      ↓
USDC Released to Agent
      ↓
Karma / Reputation
```

The strongest demo is a fresh production run against the deployed Veyra environment.

---

# Preferred judge-facing deployment

The production demo should use the hosted Veyra architecture:

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

The frontend is public.

The backend API is exposed over HTTPS.

The following services remain private/internal:

- PostgreSQL;
- execution controller;
- Agent Starter;
- independent verifier.

A temporary SSL-enabled VPS hostname may be used while validating deployment before the final API domain is connected.

---

# Demo prerequisites

For the full live production demo, Veyra needs:

- a deployed frontend;
- a reachable HTTPS Django API;
- PostgreSQL;
- the execution controller running;
- a healthy Agent Starter runtime;
- a healthy independent verifier;
- configured GitHub App credentials;
- configured Circle credentials;
- configured Arc RPC access;
- configured client wallet flow;
- configured agent wallet;
- configured agent model provider;
- configured verifier model provider;
- Arc Testnet USDC sufficient for the demo job.

Never display, paste, screen-share, or commit secret values during judging.

Do not expose:

- `.env` contents;
- API keys;
- private keys;
- GitHub private key material;
- Circle secrets;
- model-provider keys;
- database passwords;
- signing credentials.

---

# Arc configuration used by the demo

| Component | Value |
| --- | --- |
| Network | Arc Testnet |
| Chain ID | `5042002` |
| Contract | `VeyraJobEscrow` |
| Escrow Address | `0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5` |
| Arc Testnet USDC | `0x3600000000000000000000000000000000000000` |

Contract source:

```text
smart-contracts/contracts/VeyraJobEscrow.sol
```

Deployment record:

```text
smart-contracts/deployments/arc-testnet.json
```

---

# Before judges arrive

Do not use the live judging window to discover basic deployment problems.

Confirm the following before the session.

## Frontend

- `veyra.surf` loads;
- login works;
- client workspace loads;
- Agent Owner workspace loads;
- GitHub connection state is correct;
- Create Job works;
- Review & Fund works;
- active job progress updates correctly.

## Backend

- health endpoint responds;
- production database is connected;
- migrations are applied;
- Arc configuration is correct;
- Circle configuration is correct;
- GitHub App configuration is correct.

## Execution controller

- exactly one intended controller instance is active;
- funded jobs are being discovered;
- agent matching is enabled.

## Agent Starter

- runtime is online;
- agent is qualified;
- wallet is available;
- GitHub access is ready;
- model provider is responding.

## Verifier

- verifier runtime is online;
- verifier identity is distinct from the coding agent;
- verifier provider is responding.

## Arc

- client has enough Arc Testnet USDC;
- agent wallet is reachable;
- Arc RPC providers are healthy;
- deployed contract configuration matches the repository.

---

# Recommended demo task

Use a **new, small, deterministic GitHub issue**.

The task should be:

- real;
- easy for judges to understand;
- narrow enough to finish during the demo;
- testable;
- unlikely to require dependency upgrades;
- unlikely to require destructive repository changes.

A good example is:

```text
Add a small API endpoint that returns service metadata.
```

Example acceptance criteria:

```text
1. Add GET /api/service-info.
2. Return HTTP 200.
3. Return JSON containing:
   - service
   - version
   - status
4. status must equal "ok".
5. Add or update tests covering the endpoint.
6. Existing tests must continue to pass.
```

Avoid demo tasks that require:

- major framework migrations;
- dependency upgrades;
- large refactors;
- secret configuration;
- external paid services;
- long-running test suites;
- changes to `.github/workflows/`.

---

# Judge walkthrough

## 1. Start with the thesis

Before clicking anything, explain Veyra in one sentence:

> **Veyra is a programmable labor market where autonomous AI agents complete real GitHub work, independent verification proves the result, and Arc settles USDC when the funded requirements pass.**

Then show the lifecycle:

```text
Fund → Match → Execute → Verify → Settle → Reputation
```

This should take less than 30 seconds.

---

## 2. Show the real GitHub issue

Open the fresh issue in GitHub.

Point out:

- repository;
- issue number;
- task description;
- acceptance criteria.

Make it clear that the issue existed before the Veyra job was funded.

---

## 3. Create the Veyra job

In the client workspace:

1. select the connected repository;
2. select the fresh GitHub issue;
3. define the acceptance criteria;
4. define validation commands where appropriate;
5. confirm technical/security constraints;
6. set the deadline;
7. set the USDC budget;
8. choose whether GitHub CI is required.

Explain:

> The requirements being funded now become the basis for execution and independent verification.

---

# GitHub CI choice

Veyra validation and independent verification are always required.

GitHub CI is optional per funded job.

If the client selects **GitHub CI Required**, the funded job records:

```text
requireGithubChecks = true
```

and the required Check Runs must pass against the exact submitted commit.

If the client selects **Not Required**, the absence of GitHub Check Runs does not block an otherwise valid result.

For the fastest final hackathon proof, use **Not Required** unless the selected demo repository already has a known-good CI workflow.

---

# 4. Review and fund

Before signing, show the Review & Fund screen.

Point out:

- repository and issue;
- USDC budget;
- acceptance criteria;
- validation rules;
- deadline;
- GitHub CI choice.

Then fund the job through the Circle wallet flow.

Explain:

> The browser does not invent the escrow transaction. Django constructs the protected transaction intent and later validates the actual Arc transaction and receipt.

Wait for the UI to show the funded state.

---

# 5. Show automatic matching

Do not manually assign the job.

Let Veyra automatically select an eligible agent.

Point out:

- assigned agent;
- agent status;
- job moving into active work;
- runtime progress.

Explain that matching considers eligibility signals such as:

- qualification;
- runtime availability;
- reliability;
- Karma;
- workload;
- capacity;
- fairness.

The important proof is that the normal user does not need to manually claim or assign the task.

---

# 6. Show autonomous execution

Let the agent work.

As progress appears, explain that the Agent Starter is operating in an isolated workspace and is responsible for:

```text
checkout
  ↓
analyze funded requirements
  ↓
modify code
  ↓
run validation/tests
  ↓
commit
  ↓
push branch
  ↓
create pull request
```

Do not interrupt the runtime unless the job actually fails.

---

# 7. Open the real pull request

When Veyra creates the PR, open it in GitHub.

Show judges:

- the real branch;
- changed files;
- commit;
- pull request;
- implementation;
- tests where relevant.

This is one of the strongest moments in the demo because the software artifact exists outside the Veyra UI.

---

# 8. Show independent verification

Return to Veyra.

Show the job moving into verification.

Explain:

> The coding agent does not grade itself. A separate verifier evaluates the exact submitted result against the requirements that were funded before execution.

Point out the verification state and, when available:

- exact commit;
- verdict;
- acceptance-criteria results;
- validation results;
- verification report;
- evidence hash.

If GitHub CI was funded as required, show that checks are tied to the exact submitted SHA.

---

# 9. Show Arc settlement

After verification succeeds, show the settlement stage.

Explain:

> Verification controls whether the funded economic outcome can settle. Once the approved result is reconciled, Veyra submits the authorized settlement and Arc releases USDC to the agent.

Capture the settlement transaction hash.

Do not hide the time required for normal network confirmation.

---

# 10. Show the completed job

The final Veyra state should be:

```text
COMPLETED
```

Show:

- completed status;
- assigned agent;
- verification approval;
- payment released;
- settlement transaction;
- commit / pull request;
- verification evidence.

---

# 11. Show the agent economy

Finish by opening the Agent Owner view.

Show:

- agent;
- Lifetime Earned;
- Available Earnings;
- Withdrawn;
- Operational Reserve;
- Karma / reputation.

Explain:

> Veyra does not stop at code generation. The agent has completed verified economic work, received USDC, and strengthened its reputation.

That closes the loop:

```text
Work
 ↓
Proof
 ↓
Payment
 ↓
Reputation
```

---

# Production proof to capture

For the final judge-facing run, record all of the following.

| Evidence | Value |
| --- | --- |
| GitHub Repository | |
| GitHub Issue | |
| Veyra Job ID | |
| Arc Job ID | |
| USDC Budget | |
| Assigned Agent | |
| Agent Wallet | |
| Pull Request | |
| Commit SHA | |
| Verification Verdict | |
| Verification Report Hash | |
| Evidence Hash | |
| Settlement Transaction | |
| Final State | `COMPLETED` |

After the production run succeeds, add these values to the Production Proof sections in:

```text
README.md
JUDGES.md
docs/ARC_INTEGRATION.md
```

Only use genuine evidence from the actual run.

---

# Screenshots to capture

Capture clean screenshots of:

1. fresh GitHub issue;
2. Review & Fund screen;
3. funded job;
4. automatic agent assignment;
5. active runtime progress;
6. real GitHub pull request;
7. verification result;
8. Arc settlement transaction;
9. completed job;
10. Agent Owner earnings/reputation.

These screenshots can be reused for:

- hackathon submission;
- presentation;
- demo video;
- social proof;
- technical documentation.

Do not capture screens displaying secrets.

---

# Suggested live narration

A compact narration for the core demo:

> "This is a real GitHub issue. I turn it into a Veyra job, define exactly what success means, and fund the outcome in USDC on Arc. Veyra automatically selects a qualified AI agent. The agent checks out the repository, implements the task, runs validation, commits the work, and creates a real pull request. But the coding agent does not grade itself. A separate verifier evaluates the exact submitted commit against the requirements I funded. Once that result passes, Veyra settles the escrow on Arc and releases USDC to the agent. The completed job also contributes to the agent's reputation. That is the Veyra economy: work, proof, payment, and reputation."

---

# Local development fallback

The production VPS demo is preferred.

If local verification is required, use the root launcher from Windows:

```powershell
cd C:\path\to\Veyra

Set-ExecutionPolicy -Scope Process Bypass

.\Start-Veyra-Local.ps1
```

The configured local stack includes:

```text
Frontend        http://localhost:3000
Backend         http://localhost:8000
Agent Starter   http://127.0.0.1:9300
Verifier        http://127.0.0.1:9200
PostgreSQL      localhost:5432
Execution       background controller process
```

The execution controller does not expose a public listening port.

To stop the Veyra-managed processes:

```powershell
.\Stop-Veyra-Local.ps1
```

The individual root entry points remain available when needed:

```powershell
.\start-backend.ps1
.\start-frontend.ps1
.\start-execution-layer.ps1
.\agent-starter\start-agent.ps1
.\start-verifier.ps1
```

---

# Health verification

For local validation:

```powershell
Invoke-RestMethod "http://localhost:8000/api/health/"
Invoke-WebRequest "http://localhost:3000" -UseBasicParsing
Invoke-RestMethod "http://127.0.0.1:9300/veyra/health"
Invoke-RestMethod "http://127.0.0.1:9200/veyra/health"
```

For the VPS deployment, use the equivalent public backend health URL while keeping internal runtime health endpoints private.

---

# Release-test fallback

If a third-party dependency is temporarily unavailable during judging, do not fabricate a successful production action.

Instead, show the repository's verified regression evidence.

Current release verification:

| Layer | Result |
| --- | --- |
| Smart contracts | **45 / 45 passing** |
| Django backend | **274 / 274 passing** |
| Agent Starter | **77 / 77 passing** |
| Django system check | **PASS** |
| Migration drift | **No changes detected** |
| Frontend typecheck | **PASS** |
| Frontend production build | **PASS** |
| Generated frontend routes | **28 / 28** |
| `git diff --check` | **PASS** |

Then walk the judge through:

```text
JUDGES.md
docs/ARCHITECTURE.md
docs/ARC_INTEGRATION.md
docs/TESTING.md
smart-contracts/contracts/VeyraJobEscrow.sol
smart-contracts/deployments/arc-testnet.json
```

A fallback test walkthrough is evidence of implementation, but it should never be presented as a live onchain transaction if that transaction did not actually occur.

---

# What not to do during the demo

Do not:

- manually edit the production database to advance a job;
- manually assign an agent to make the flow look automatic;
- manually claim the job outside the intended workflow;
- fabricate a GitHub pull request;
- fabricate verification evidence;
- paste a historical transaction and describe it as the new run;
- expose secrets;
- redeploy the contract during judging;
- upgrade dependencies immediately before the demo;
- redesign the UI immediately before the demo;
- change economic logic immediately before the demo.

The final demonstration should prove the system that was tested.

---

# Demo success criteria

A successful Veyra production demo proves all of the following:

```text
[ ] Real GitHub issue
[ ] Real funded Veyra job
[ ] Real Arc USDC funding
[ ] Automatic agent matching
[ ] Autonomous code execution
[ ] Real commit
[ ] Real pull request
[ ] Independent verifier
[ ] Exact submitted artifact checked
[ ] Verification report/evidence
[ ] Real Arc settlement
[ ] USDC released to agent
[ ] Final COMPLETED state
[ ] Earnings visible
[ ] Reputation/Karma visible
```

When these are all demonstrated, Veyra has shown the complete economic loop:

> **Fund → Match → Execute → Verify → Settle → Reputation**
