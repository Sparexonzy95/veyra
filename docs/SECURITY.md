# Veyra Security

## Security model

Veyra combines autonomous code execution, GitHub access, wallet infrastructure, and onchain settlement.

That means the system must protect several trust boundaries at once:

```text
User
  ↓
Frontend
  ↓
Django Control Plane
  ↓
Execution Controller
  ↓
Agent Runtime
  ↓
GitHub Repository

Separate path:
Independent Verifier
  ↓
Verification Evidence
  ↓
Settlement Authority
  ↓
Arc Escrow
```

The core rule is:

> **No single browser, coding agent, verifier, RPC provider, or retry path is trusted to determine the final economic outcome by itself.**

---

# Security objectives

Veyra is designed to protect:

- client funds;
- agent earnings;
- GitHub repository access;
- funded job requirements;
- runtime identities;
- model-provider credentials;
- private signing material;
- settlement authority;
- verification integrity;
- execution workspaces;
- replay-sensitive workflow state.

The architecture separates:

**who requests work, who performs work, who verifies work, and who settles funds.**

---

# Secrets and private material

The following must remain outside source control:

```text
.env
.env.*
private keys
mnemonics
GitHub App private keys
Circle credentials
model-provider API keys
database passwords
runtime identities
runtime private signing keys
wallet signing material
production logs containing secrets
local databases
temporary workspaces
```

Safe templates may be committed as:

```text
.env.example
```

Real values belong in the host-managed secret boundary.

---

# Runtime identities

Agent and verifier runtimes use separate identities.

Private runtime signing material remains local to the corresponding runtime environment.

For Agent Starter, private identity material belongs under its ignored runtime state directory, such as:

```text
.veyra-runtime/
```

Django stores only the server-side material required to authenticate and validate runtime interactions, including hashed connection credentials where supported by the current implementation.

Private Ed25519 signing material must not be copied into frontend code or source control.

---

# Worker and verifier separation

The coding agent does not verify its own work.

The verifier uses a distinct runtime role and identity.

Recommended production separation includes:

- separate runtime identity;
- separate model-provider credentials;
- separate environment file;
- separate logs;
- separate workspace;
- restricted repository access appropriate to verification.

The verifier should not be given unnecessary write access.

The verifier should not directly hold the contract settlement-authority key.

---

# Contract authority

The current Arc Testnet contract requires a configured authority for owner-only settlement operations.

That authority belongs to the backend settlement boundary.

It should never be exposed to:

- browser JavaScript;
- Agent Starter;
- verifier;
- GitHub repository content;
- user-controlled request payloads.

For a hackathon VPS, the key must remain a server-only secret with strict filesystem permissions.

For hardened production use, move this signing authority into managed infrastructure such as:

- KMS;
- HSM;
- managed key custody.

---

# Frontend trust boundary

The browser is not trusted to define protected economic operations.

The frontend may request an action, but Django determines protected values such as:

- escrow target;
- expected contract;
- protected calldata;
- expected job;
- expected wallet;
- funded requirements;
- settlement eligibility.

The browser must not be able to replace a protected contract target or calldata and have that new value accepted as authoritative.

---

# Funding transaction controls

Django constructs the expected funding intent.

After the client signs through the supported Circle user-controlled wallet flow, the application does not trust the frontend's claim that funding succeeded.

Django reconciles the actual transaction and Arc receipt.

Relevant checks include:

- expected sender;
- expected destination;
- expected calldata or calldata commitment;
- transaction status;
- allowance state where applicable;
- `JobCreated` evidence;
- resulting onchain job ID.

This turns the chain result, not the browser response, into the funding proof.

---

# GitHub App security

Veyra uses a GitHub App installation rather than a broad user OAuth token.

Important controls include:

- installation-scoped access;
- repository-scoped installation permissions;
- short-lived installation tokens;
- signed installation state;
- server-side App private key;
- webhook signature verification.

The browser never needs the GitHub App private key or installation token.

A GitHub OAuth `code` must never be treated as an `installation_id`.

See:

```text
docs/GITHUB_APP_SETUP.md
```

---

# Repository authorization

A repository becomes eligible for Veyra work through the client's approved GitHub App installation.

The backend should treat GitHub's installation scope as authoritative.

The browser must not be able to gain access to a repository merely by submitting an arbitrary owner/repository string.

---

# Execution workspace isolation

Autonomous work runs inside an isolated job workspace.

The runtime should not execute directly inside:

- the Veyra application repository;
- secret directories;
- runtime identity directories;
- system configuration directories.

Job workspaces should be disposable and outside web roots and secret locations.

Example production location:

```text
/var/lib/veyra/workspaces
```

---

# Funded path policy

Veyra constrains which repository paths autonomous execution may modify.

Protected paths include:

```text
.env*
.git/
.github/workflows/
```

The path policy also rejects unsafe or ambiguous path forms such as:

- traversal outside the workspace;
- absolute paths where relative repository paths are required;
- unknown funded targets;
- ambiguous targets;
- protected internal files.

This prevents an agent from using a normal funded task to rewrite sensitive runtime configuration or CI policy.

---

# GitHub CI integrity

Veyra validation and independent verification are mandatory.

GitHub CI is client-selectable.

If a funded job records:

```text
requireGithubChecks = true
```

the required Check Runs must pass against the exact submitted commit.

If GitHub CI was not funded as required, the absence of Check Runs does not block an otherwise valid result.

Because `.github/workflows/` is protected, the coding agent cannot simply weaken the workflow to manufacture a pass.

---

# Exact artifact verification

A pull request existing is not enough.

Verification is tied to the exact submitted artifact.

Relevant evidence includes:

- repository;
- branch;
- commit;
- pull request;
- exact head SHA;
- funded requirements;
- validation output;
- verifier evidence.

The verifier evaluates the actual result submitted for the funded job.

---

# Runtime authentication and replay controls

Runtime communication is constrained using the identity and assignment state maintained by the control plane.

Security-relevant controls include:

- scoped runtime credentials;
- hashed connection credentials;
- signed runtime responses where supported;
- assignment identity validation;
- lease state;
- replay protection;
- strict job/assignment binding.

A runtime response should not be accepted merely because it contains a syntactically valid payload.

It must correspond to the expected runtime, assignment, and lifecycle state.

---

# Execution leases

Execution leases help prevent multiple actors from independently advancing the same assignment.

PostgreSQL stores the durable workflow state used by the controller.

The design is intended to prevent duplicated controller activity from creating duplicated logical progress.

The execution controller should run exactly once per intended database lease domain.

---

# Capacity safety

Agent capacity is part of execution safety.

An agent that is already coding should not be repeatedly assigned beyond its configured capacity.

Capacity is held through the active coding/submission stages and released when the workflow reaches a non-coding state.

Retry/rework paths reacquire capacity as required.

Pending withdrawal operations can also temporarily remove an agent from automatic matching where wallet-operation conflicts must be avoided.

---

# Settlement idempotency

Economic retries are handled differently from ordinary stateless HTTP retries.

Veyra persists the intended settlement transaction data before broadcast where required by the current workflow.

If a provider or response fails, Veyra reconciles relevant chain state before attempting another settlement action.

The goal is:

```text
One verified job
      ↓
One logical settlement
      ↓
One final economic outcome
```

A network timeout must not become permission to pay twice.

---

# RPC safety

Every Arc RPC provider must report the expected network:

```text
Chain ID: 5042002
```

A provider reporting the wrong chain is rejected.

Provider failover should preserve the same logical economic action.

For rebroadcast scenarios, the system should reuse the same signed transaction envelope where appropriate rather than inventing a new transaction solely because the first RPC endpoint failed.

---

# Withdrawal security

Agent-owner withdrawals use a persistent workflow rather than a frontend-only state.

Security controls include:

- owner authorization;
- destination validation;
- amount validation;
- earned-funds accounting;
- operational reserve separation;
- active-work checks;
- pending state;
- transaction reconciliation;
- final completion/failure state.

Operational wallet funding is not counted as earned income.

A successful underlying transaction can be reconciled even if the immediate browser response is lost.

---

# Earnings accounting

The Agent Owner experience separates:

- Lifetime Earned;
- Available Earnings;
- Withdrawn;
- Operational Reserve.

This avoids presenting operational wallet funding as income.

The accounting boundary is important because autonomous agents may require wallet funding for operations that should not become withdrawable earnings.

---

# Database security

Production uses PostgreSQL.

The database should not be exposed publicly.

Recommended binding:

```text
127.0.0.1:5432
```

or a private network interface when using a separate database host.

Use:

- a dedicated database;
- a dedicated application user;
- a strong password;
- least-privilege permissions;
- backups;
- restricted network access.

Do not use database superuser credentials for normal application traffic.

---

# VPS service isolation

Production services should run as non-root users.

Recommended separation:

```text
veyra-web
veyra-agent
veyra-verifier
```

The execution controller may share the backend application account or use its own service user depending on the deployment model.

Separate service identities reduce the impact of compromise across:

- provider credentials;
- runtime identity;
- workspaces;
- logs;
- settlement configuration.

---

# Network exposure

Public:

```text
22   SSH
80   HTTP / redirect / certificate flow
443  HTTPS
```

Private:

```text
5432 PostgreSQL
8000 Gunicorn
9200 Verifier
9300 Agent Starter
```

The execution controller does not need a public listening port.

Do not expose Agent Starter or verifier health/runtime ports publicly unless a future hardened architecture explicitly requires it.

---

# TLS and secure cookies

The backend should sit behind HTTPS.

Production Django configuration should use secure settings appropriate to a reverse-proxy deployment.

Review:

```text
DEBUG
ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS
CORS_ALLOWED_ORIGINS
SESSION_COOKIE_SECURE
CSRF_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER
```

Use HSTS after confirming HTTPS is correctly configured.

Do not use wildcard credentialed CORS for production.

---

# CORS and CSRF

Final trusted frontend origin:

```text
https://veyra.surf
```

Final backend origin:

```text
https://api.veyra.surf
```

Only allow required origins.

Temporary `sslip.io` deployment origins may be added while validating the VPS and should be removed when no longer needed.

---

# Logging

Logs must be useful without becoming a secret store.

Do not log:

- private keys;
- API keys;
- Authorization headers;
- raw model-provider secrets;
- GitHub App private keys;
- Circle secrets;
- database passwords;
- settlement signing material;
- full sensitive signed state values.

Use structured logging, rotation, and retention appropriate to the host.

---

# Dependency safety

A passing test suite does not mean every dependency is permanently safe.

Before a hardened production launch:

- review dependency advisories;
- plan patch cadence;
- remove unused dependencies;
- lock dependency versions;
- review transitive risk;
- test upgrades before production rollout.

Do not perform broad dependency upgrades immediately before a hackathon demo simply to silence non-blocking deprecation warnings.

---

# Smart-contract safety

The deployed `VeyraJobEscrow` test suite currently covers major economic controls including:

- funding validation;
- claiming;
- role separation;
- submission commitments;
- payout;
- rejection;
- refunds;
- expiry;
- verifier timing;
- authorization;
- pause behavior;
- fee-on-transfer rejection;
- reentrancy protection;
- escrow accounting;
- duplicate payout/refund prevention.

Current release result:

```text
45 passing
```

A passing test suite is strong implementation evidence, but it is not a substitute for an independent production audit.

---

# Backup and recovery

Before a production release:

- back up PostgreSQL;
- preserve the previously working application release;
- record the currently deployed commit;
- preserve host-managed secret files;
- verify migration state.

Do not roll back finalized Arc transactions.

If an offchain process fails after a chain transaction, reconcile chain state before creating another economic action.

---

# Incident response

A production security plan should define what to do if:

- a model-provider key leaks;
- a GitHub App key leaks;
- a Circle credential leaks;
- the settlement key leaks;
- a runtime identity is compromised;
- a VPS is compromised;
- an RPC endpoint behaves incorrectly;
- a withdrawal is disputed;
- a webhook secret leaks.

At minimum, prepare to:

- revoke/rotate credentials;
- disable affected runtime identities;
- pause applicable application activity;
- preserve logs/evidence;
- reconcile outstanding onchain state;
- restore from known-good infrastructure.

---

# Security verification checklist

Before judge-facing production use:

```text
[ ] No tracked .env files
[ ] No tracked private keys
[ ] No tracked runtime identities
[ ] No tracked database files
[ ] GitHub App private key remains server-side
[ ] Circle secrets remain server-side
[ ] Model-provider keys remain server-side
[ ] Settlement authority remains server-side
[ ] Worker and verifier identities are distinct
[ ] PostgreSQL is private
[ ] Agent Starter is private
[ ] Verifier is private
[ ] HTTPS works
[ ] CORS is restricted
[ ] CSRF trusted origins are correct
[ ] Secure cookies are enabled
[ ] Protected repository paths remain enforced
[ ] GitHub CI policy matches funded requirements
[ ] Exact submitted SHA is verified
[ ] Settlement retry path remains idempotent
[ ] Withdrawal reconciliation remains enabled
```

---

# Security review map

### Django settings

```text
backend/config/settings.py
```

### Arc transaction handling

```text
backend/blockchain/
backend/wallets/
```

### GitHub integration

```text
backend/jobs/github_app.py
backend/jobs/github_views.py
docs/GITHUB_APP_SETUP.md
```

### Runtime / execution security

```text
agent-starter/
backend/workers/
```

### Verifier

```text
verifier/
backend/workers/execution_verification.py
```

### Smart contract

```text
smart-contracts/contracts/VeyraJobEscrow.sol
smart-contracts/test/
```

---

# Security thesis

Veyra does not assume autonomous software agents are inherently trustworthy.

Instead, it constrains them with:

**scoped access, isolated workspaces, funded requirements, exact-artifact verification, independent review, durable workflow state, and programmable settlement.**

> **The agent can work autonomously without being given unilateral control over verification or payment.**
