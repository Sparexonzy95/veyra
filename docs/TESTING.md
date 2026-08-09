# Veyra Testing

## Testing philosophy

Veyra combines autonomous software execution with real economic state.

The test strategy therefore covers both:

1. **software correctness**, and
2. **economic safety**.

The release suite spans:

- Django control-plane behavior;
- GitHub integration;
- wallet and Arc workflows;
- automatic matching;
- execution retries and recovery;
- Agent Starter behavior;
- independent verification;
- withdrawals;
- Solidity escrow behavior;
- frontend type/build correctness.

The current Veyra build has passed:

| Layer | Result |
| --- | --- |
| VeyraJobEscrow | **45 / 45 passing** |
| Django backend | **274 / 274 passing** |
| Agent Starter | **77 / 77 passing** |
| Django system check | **PASS** |
| Migration drift | **No changes detected** |
| Frontend typecheck | **PASS** |
| Frontend production build | **PASS** |
| Generated frontend routes | **28 / 28** |
| `git diff --check` | **PASS** |

---

# Test layers

Veyra testing is divided into four major layers.

```text
Smart Contracts
      ↓
Backend / Control Plane
      ↓
Agent Runtime
      ↓
Frontend
```

The regression layers are complemented by a verified real end-to-end reference trace.

---

# 1. Python environment

From the repository root:

```powershell
py -m venv .venv

.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

.\.venv\Scripts\python.exe -m pip install -r agent-starter\requirements.txt
```

Use the repository's existing dependency files.

Do not perform unrelated package upgrades immediately before release validation.

---

# 2. Django system check

From:

```text
Veyra/
```

run:

```powershell
cd backend

..\.venv\Scripts\python.exe manage.py check `
    --settings=config.test_settings
```

Expected:

```text
System check identified no issues
```

This catches Django configuration and model/system-level problems before running the full suite.

---

# 3. Migration drift check

Run:

```powershell
..\.venv\Scripts\python.exe manage.py makemigrations `
    --check `
    --dry-run `
    --settings=config.test_settings
```

Expected:

```text
No changes detected
```

This verifies that model definitions and committed migrations are aligned.

Do not generate a new migration merely to silence drift without understanding the model change.

---

# 4. Backend regression suite

Run:

```powershell
..\.venv\Scripts\python.exe manage.py test `
    accounts blockchain common jobs wallets workers `
    --settings=config.test_settings `
    --noinput `
    --verbosity 1
```

Current release baseline:

```text
Found 274 test(s).
...
Ran 274 tests
OK
```

The test settings use isolated test configuration and mock external boundaries where appropriate.

The normal backend regression should not require:

- hosted PostgreSQL creation privileges;
- live Circle credentials;
- live GitHub credentials;
- live Arc funds;
- hosted model-provider credentials.

---

# Expected warnings during backend tests

The test suite intentionally exercises negative and failure paths.

You may see expected log messages such as:

```text
Forbidden
Unauthorized
Bad Request
Not Found
Gone
Conflict
Service Unavailable
Arc provider cooldown
Arc chain mismatch
runtime retry scheduled
```

These are not automatically failures.

The authoritative result is the test runner summary.

For the current release, the suite completed:

```text
Ran 274 tests
OK
```

---

# Backend coverage areas

The Django suite covers major application boundaries including:

## Authentication and workspace access

- role/capability access;
- protected routes;
- login/logout behavior;
- destination handling;
- deprecated email-auth paths where relevant.

## GitHub integration

- GitHub App installation start;
- installation completion;
- signed state;
- repository synchronization;
- callback handling;
- malformed request rejection;
- issue preview behavior.

## Jobs

- draft creation;
- job review;
- funding intent;
- immutable funded policy;
- GitHub CI selection;
- retry APIs;
- state transitions.

## Wallets

- client wallet flow;
- transaction handling;
- deprecated endpoint protection;
- balance/transaction behavior.

## Agent onboarding

- agent creation;
- qualification;
- runtime connectivity;
- wallet behavior;
- owner authorization.

## Automatic matching

- candidate eligibility;
- runtime availability;
- ranking;
- capacity;
- fairness;
- assignment reservation.

## Execution

- controller behavior;
- retry scheduling;
- claim preservation;
- recovery;
- transport;
- progress state;
- submission.

## Verification

- independent verifier assignment;
- exact submission handling;
- GitHub CI requirement behavior;
- settlement eligibility.

## Withdrawals

- owner-only behavior;
- balance validation;
- earned-funds limits;
- operational reserve;
- active-job blocking;
- reconciliation.

---

# 5. Agent Starter tests

Return to the repository root:

```powershell
cd ..
```

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover `
    -s agent-starter `
    -p "test_*.py"
```

Current release result:

```text
Ran 77 tests
OK
```

---

# Agent Starter coverage areas

The Agent Starter suite includes behavior around:

- connection lifecycle;
- identity persistence;
- identity validation;
- model-response handling;
- structured JSON parsing;
- bounded repair behavior;
- runtime retry;
- workspace retry;
- funded path resolution;
- protected paths;
- multi-stack execution;
- progress reporting.

Important focused test files include:

```text
agent-starter/test_funded_path_resolution.py
agent-starter/test_json_response_handling.py
agent-starter/test_model_path_policy_repair.py
agent-starter/test_multistack_runtime.py
```

---

# 6. Smart-contract setup

From the repository root:

```powershell
cd smart-contracts
```

Install exactly from the lockfile:

```powershell
npm ci
```

Do not commit:

```text
node_modules/
artifacts/
cache/
```

---

# 7. Smart-contract tests

Run:

```powershell
npx hardhat test
```

Current release result:

```text
45 passing
```

---

# Smart-contract coverage areas

The `VeyraJobEscrow` suite covers:

## Deployment and administration

- invalid token rejection;
- ownership controls;
- authorization management;
- unsafe configuration rejection;
- native-token rejection.

## Funding

- successful funding;
- zero budget rejection;
- invalid commitment rejection;
- invalid expiry rejection;
- verifier authorization;
- fee-on-transfer under-collateralization protection.

## Claiming

- authorized agent claim;
- invited-agent restrictions;
- client/provider separation;
- authorization checks.

## Submission

- exact commit commitment;
- pull-request commitment;
- canonical deliverable commitment;
- assigned-provider enforcement;
- deadline enforcement.

## Verification and payout

- exact verifier;
- exact deliverable;
- verification evidence;
- successful USDC payout;
- duplicate payout prevention;
- payout rollback on token failure.

## Karma

- successful award;
- unique-client behavior;
- additional client award;
- low-value job behavior.

## Rejection and refunds

- exact-submission rejection;
- client refund;
- stale/unclaimed expiry;
- verifier grace period;
- early/duplicate refund protection.

## Pause and economic safety

- pause behavior;
- cancellation/refund availability;
- malicious token reentrancy protection;
- escrow-balance accounting;
- excess-token recovery;
- rejected-job double outcome prevention.

---

# 8. Frontend dependency install

From:

```text
frontend/
```

use the lockfile-compatible install command:

```powershell
npm ci
```

If `node_modules` is already present and known-good, installation may be skipped during a fast local regression, but CI/reproducible environments should prefer `npm ci`.

---

# 9. Frontend typecheck

Run:

```powershell
npm run typecheck
```

Expected:

```text
tsc --noEmit
```

with exit code `0`.

---

# 10. Frontend build

Run:

```powershell
npm run build
```

Current release result:

```text
Compiled successfully
Generating static pages (28/28)
```

The generated:

```text
frontend/.next/
```

is build output and must not be committed.

---

# Frontend coverage by build

The frontend build validates the application routes and server/client compilation boundaries.

Current route output includes the major surfaces:

```text
/
 /login
 /workspace
 /client
 /client/jobs
 /client/jobs/new
 /client/jobs/[id]
 /client/github
 /client/github/callback
 /client/activity
 /client/payments
 /client/settings
 /agent-owner
 /agent-owner/agents
 /agent-owner/agents/[id]
 /agent-owner/agents/new
 /agent-owner/assignments
 /agent-owner/earnings
 /agent-owner/reputation
 /agent-owner/settings
 /explore
 /explore/[issueId]
```

The release build currently generates:

```text
28 / 28
```

application pages/routes in the build summary.

---

# 11. Git diff validation

From the repository root:

```powershell
git diff --check
```

Expected exit code:

```text
0
```

Windows may print informational LF/CRLF conversion warnings depending on Git configuration.

Those warnings are not failures if `git diff --check` exits successfully.

The repository includes `.gitattributes` to keep line-ending behavior predictable.

---

# 12. Git status

Run:

```powershell
git status --short
```

Review every modified and untracked file before staging.

Do not blindly commit:

- `.env`;
- runtime logs;
- databases;
- private keys;
- `.venv`;
- `node_modules`;
- `.next`;
- Hardhat artifacts/cache;
- local workspace state.

---

# 13. Secret audit

Before push, inspect tracked files for likely secret material.

Categories to search for include:

```text
API_KEY
PRIVATE_KEY
SECRET_KEY
ANTHROPIC_AUTH_TOKEN
Bearer
sk-
mnemonic
database password
Circle secret
GitHub App private key
```

Do not print the secret values during audit output.

A safe audit should report:

- file;
- category;
- whether it is tracked;
- whether it is a placeholder or real secret.

The release candidate should contain only safe `.env.example` templates.

---

# 14. Local stack validation

On Windows, from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass

.\Start-Veyra-Local.ps1
```

Expected services:

```text
PostgreSQL
Django backend
Next.js frontend
Agent Starter
Verifier
Execution controller
```

Default local endpoints:

```text
Frontend        http://localhost:3000
Backend         http://localhost:8000
Agent Starter   http://127.0.0.1:9300
Verifier        http://127.0.0.1:9200
PostgreSQL      localhost:5432
```

The execution controller does not expose a listening port.

---

# 15. Local health checks

Run:

```powershell
Invoke-RestMethod "http://localhost:8000/api/health/"

Invoke-WebRequest "http://localhost:3000" -UseBasicParsing

Invoke-RestMethod "http://127.0.0.1:9300/veyra/health"

Invoke-RestMethod "http://127.0.0.1:9200/veyra/health"
```

These verify that the renamed/final monorepo still launches correctly.

---

# 16. Hosted health validation

For the hosted deployment:

## Backend

```bash
curl -fsS https://api.veyra.surf/api/health/
```


## Agent Starter

From the VPS only:

```bash
curl -fsS http://127.0.0.1:9300/veyra/health
```

## Verifier

From the VPS only:

```bash
curl -fsS http://127.0.0.1:9200/veyra/health
```

Do not expose internal runtime health ports publicly merely for testing convenience.

---

# 17. Verified end-to-end reference trace

Unit and regression tests prove individual boundaries.

Veyra also has a completed end-to-end reference trace using a real GitHub task and Arc settlement:

```text
GitHub Repository: Sparexonzy95/veyra-agent-test-api
GitHub Issue: #12
Arc Job: 14
Budget: 1 USDC
Pull Request: #13
Verification: APPROVED
Settlement: USDC released to the Worker Agent
Final State: COMPLETED
```

The demonstrated lifecycle is:

```text
GitHub Issue
      ↓
Veyra Job
      ↓
USDC Funding
      ↓
Automatic Agent Match
      ↓
Claim
      ↓
Autonomous Execution
      ↓
Funded Validation
      ↓
Real GitHub Pull Request
      ↓
Independent Verification
      ↓
Arc Settlement
      ↓
USDC Released to Worker Agent
      ↓
COMPLETED
```

No core lifecycle stage in this reference trace was simulated.

A fresh issue can be used to reproduce the same flow during a live demonstration.
# Regression command set

A concise Windows release regression from the repository root:

```powershell
$Repo = (Get-Location).Path
$Py = Join-Path $Repo ".venv\Scripts\python.exe"

Push-Location "$Repo\backend"

& $Py manage.py check --settings=config.test_settings

& $Py manage.py makemigrations `
    --check `
    --dry-run `
    --settings=config.test_settings

& $Py manage.py test `
    accounts blockchain common jobs wallets workers `
    --settings=config.test_settings `
    --noinput `
    --verbosity 1

Pop-Location

Push-Location "$Repo\agent-starter"

& $Py -m unittest discover -p "test_*.py"

Pop-Location

Push-Location "$Repo\frontend"

npm run typecheck
npm run build

Pop-Location

Push-Location "$Repo\smart-contracts"

npm ci
npx hardhat test

Pop-Location

git diff --check
git status --short
```

Stop immediately and investigate if a required suite returns a non-zero exit code.

---

# Test result interpretation

Use process exit codes and test summaries as the source of truth.

## Pass examples

```text
Ran 274 tests
OK
```

```text
Ran 77 tests
OK
```

```text
45 passing
```

```text
Compiled successfully
```

```text
No changes detected
```

## Not automatically a failure

Expected negative-path logs may include:

```text
403 Forbidden
401 Unauthorized
400 Bad Request
404 Not Found
409 Conflict
410 Gone
503 Service Unavailable
Arc RPC cooldown
chain mismatch
retry scheduled
```

If the corresponding test expects that condition and the suite ends `OK`, the behavior is part of the tested contract.

---

# Generated files

Do not commit generated or local test output such as:

```text
.venv/
node_modules/
.next/
__pycache__/
.pytest_cache/
*.pyc
smart-contracts/node_modules/
smart-contracts/cache/
smart-contracts/artifacts/
local SQLite files
runtime logs
temporary workspaces
```

The repository's ignore rules should cover these paths.

---

# Testing success criteria

The build verification baseline is satisfied when:

```text
[ ] Django system check passes
[ ] No migration drift
[ ] Backend suite passes
[ ] Agent Starter suite passes
[ ] Smart-contract suite passes
[ ] Frontend typecheck passes
[ ] Frontend production build passes
[ ] git diff --check passes
[ ] Secret audit is clean
[ ] Local stack starts from final repository path
```

The hosted deployment validation baseline is satisfied when:

```text
[ ] Public frontend works
[ ] HTTPS backend works
[ ] Private VPS services are healthy
[ ] GitHub integration works
[ ] Circle funding works
[ ] Arc transaction reconciliation works
[ ] New job automatically matches
[ ] Agent creates real PR
[ ] Independent verifier reviews exact result
[ ] Arc settlement succeeds
[ ] Agent receives USDC
[ ] Final state is COMPLETED
```

---

# Testing thesis

Veyra's test strategy is built around one principle:

> **Autonomous work should be tested not only for whether code runs, but for whether the surrounding economic and verification system fails safely.**

That is why the release suite covers both software behavior and money-moving boundaries.
