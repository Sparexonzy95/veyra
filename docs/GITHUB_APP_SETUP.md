# Veyra GitHub App Integration

## Purpose

Veyra connects clients to repositories through a **GitHub App installation**.

The integration is installation-based, not ordinary GitHub OAuth user authorization.

That distinction is essential because Veyra needs a GitHub App `installation_id` in order to mint installation access tokens and work only with the repositories that the client explicitly approved.

The high-level flow is:

```text
Veyra Client
    ↓
Connect GitHub
    ↓
GitHub App Installation
    ↓
Approved Account / Repositories
    ↓
installation_id
    ↓
Veyra Backend
    ↓
Installation Token
    ↓
Repository + Issue Access
```

Veyra never treats a GitHub OAuth `code` as an installation identifier.

---

# Why Veyra uses a GitHub App

A GitHub App gives Veyra a repository-scoped integration model.

This allows a client to choose which repositories Veyra may access instead of granting broad account-wide access.

The installation model also fits the Veyra job lifecycle:

```text
Connect GitHub App
      ↓
Select approved repository
      ↓
Select real issue
      ↓
Create funded Veyra job
      ↓
Agent executes
      ↓
Real branch / commit / pull request
      ↓
Independent verification
```

The GitHub App is therefore a core boundary between Veyra's autonomous runtime and the repositories a client has authorized.

---

# Installation round trip

## 1. Client starts the connection

The client opens:

```text
/client/github
```

and clicks:

```text
Connect GitHub
```

The frontend requests an installation URL from Django:

```http
POST /api/v1/client/github/app/install/start/
```

---

## 2. Django creates the installation URL

The backend returns a GitHub App installation URL in this form:

```text
https://github.com/apps/<GITHUB_APP_SLUG>/installations/new?state=<signed-state>
```

The `state` value is short-lived and signed.

It binds the installation flow to:

- the signed-in Veyra user;
- the expected installation flow;
- the intended return context.

The frontend should only navigate to the expected GitHub App installation URL shape.

This prevents the browser from substituting an arbitrary destination supplied as installation configuration.

---

# 3. User selects GitHub access

GitHub asks the user to choose:

- an account or organization;
- all repositories or selected repositories, depending on the App configuration and installation choice.

The selected repositories become the scope of the GitHub App installation.

---

# 4. GitHub returns to the Setup URL

GitHub returns the browser to the App's configured **Setup URL**.

For Veyra, the callback route is:

```text
/client/github/callback
```

The exact origin depends on the environment.

Examples:

```text
Local:
http://localhost:3000/client/github/callback

Production:
https://veyra.surf/client/github/callback
```

GitHub can return different parameter combinations depending on what happened.

| Outcome | Parameters |
| --- | --- |
| New installation | `installation_id`, `setup_action=install`, `state` |
| Repository access updated | `installation_id`, `setup_action=update`, `state` |
| Organization approval requested | `setup_action=request` and no `installation_id` |
| User authorization also enabled | May additionally include `code` |

Important:

> `code` is an OAuth authorization code. It is not the GitHub App `installation_id`.

---

# 5. Veyra completes the installation

The callback page posts the installation result to Django:

```http
POST /api/v1/client/github/app/install/complete/
```

The normal completion payload contains the relevant:

```text
installation_id
state
```

Django validates the signed state against the current Veyra user.

If valid, the backend:

1. links the GitHub App installation to the Veyra account;
2. records the installation identifier;
3. mints installation access as required;
4. synchronizes repositories approved for that installation.

The client can then use those repositories when creating Veyra jobs.

---

# Installation sequence

```text
Client Browser
     │
     │ POST install/start
     ▼
Veyra Django
     │
     │ signed installation URL
     ▼
GitHub App
     │
     │ user selects repositories
     ▼
GitHub Setup Redirect
     │
     │ installation_id + state
     ▼
Veyra Frontend Callback
     │
     │ POST install/complete
     ▼
Veyra Django
     │
     ├─ validate state
     ├─ link installation
     └─ sync approved repositories
```

---

# Required GitHub App settings

Configure the GitHub App from the GitHub App settings page.

## Setup URL

The **Setup URL** is the critical callback for the installation flow.

### Local development

```text
http://localhost:3000/client/github/callback
```

### Production

```text
https://veyra.surf/client/github/callback
```

Use the same callback path on the appropriate frontend origin.

---

# Redirect on update

Enable the option that redirects users back to the Setup URL after installation repository access is changed.

This allows Veyra to receive the updated installation context and synchronize the new approved repository scope.

---

# Webhook URL

Veyra's backend webhook endpoint is:

```text
/api/v1/client/github/app/webhook/
```

Production shape:

```text
https://api.veyra.surf/api/v1/client/github/app/webhook/
```

During temporary VPS validation, use the corresponding HTTPS backend hostname.

For local development, the backend requires an HTTPS tunnel or equivalent externally reachable endpoint if GitHub needs to deliver real webhook events.

Do not expose the local Django development server directly to the public internet.

---

# Setup URL vs OAuth callback URL

These two GitHub settings are not interchangeable.

## GitHub App Setup URL

Used for:

```text
App installation
repository selection
installation updates
installation_id
```

Expected Veyra route:

```text
/client/github/callback
```

## User authorization callback URL

Used for:

```text
GitHub OAuth user authorization
```

That flow returns an OAuth:

```text
code
```

It does **not** replace the installation flow and should not be expected to provide the `installation_id` Veyra needs.

If the GitHub App has user authorization enabled, GitHub may send `code` alongside installation parameters.

Veyra still uses the real `installation_id` for repository installation access.

---

# Backend environment variables

The backend requires GitHub App configuration.

| Variable | Purpose |
| --- | --- |
| `GITHUB_APP_ID` | Numeric GitHub App ID used when creating the App JWT |
| `GITHUB_APP_SLUG` | Exact slug from `github.com/apps/<slug>` |
| `GITHUB_APP_PRIVATE_KEY` | RSA private key value for GitHub App authentication |
| `GITHUB_APP_PRIVATE_KEY_PATH` | Alternative path to the RSA private key |
| `GITHUB_WEBHOOK_SECRET` | Secret used to verify GitHub webhook signatures |
| `GITHUB_APP_INSTALL_URL` | Optional installation URL override |
| `GITHUB_APP_STATE_TTL_SECONDS` | Optional signed-state lifetime, default `900` seconds |

Use either:

```text
GITHUB_APP_PRIVATE_KEY
```

or:

```text
GITHUB_APP_PRIVATE_KEY_PATH
```

according to the backend configuration already supported by the repository.

Do not commit the actual private key.

---

# GITHUB_APP_SLUG

`GITHUB_APP_SLUG` must exactly match the slug visible in the GitHub App URL.

Example shape:

```text
https://github.com/apps/<slug>
```

The backend uses the slug to construct:

```text
https://github.com/apps/<slug>/installations/new
```

If the slug is missing, the installation URL cannot be constructed correctly.

Veyra should return a configuration error rather than producing a malformed URL such as:

```text
https://github.com/apps//installations/new
```

A malformed installation URL can send the user to a GitHub 404 and eventually back to the application without the expected installation parameters.

---

# Optional GITHUB_APP_INSTALL_URL override

If:

```text
GITHUB_APP_INSTALL_URL
```

is set, it must still represent a GitHub App installation endpoint.

Expected ending:

```text
/installations/new
```

An ordinary OAuth authorization URL is not a valid substitute.

The override exists for explicit configuration, not to bypass installation semantics.

---

# Signed state

Veyra uses signed state to protect the installation round trip.

The state is:

- short-lived;
- tied to the Veyra user;
- validated server-side;
- not a GitHub access token.

Default lifetime:

```text
900 seconds
```

when `GITHUB_APP_STATE_TTL_SECONDS` is not overridden.

The state value should never be printed in full in logs.

---

# Frontend configuration

The frontend does not need to construct the GitHub installation URL itself.

The URL comes from Django.

This avoids duplicating sensitive GitHub App configuration in browser code.

The frontend's responsibilities are:

1. ask Django to start the installation;
2. validate that the returned navigation target has the expected GitHub App installation shape;
3. send the browser to GitHub;
4. receive the Setup URL callback;
5. send `installation_id` and `state` back to Django;
6. display success, pending approval, or actionable failure.

---

# Diagnosing an empty callback

If the browser reaches:

```text
/client/github/callback
```

with no useful query parameters, Veyra should not claim that the installation succeeded.

The UI should report a configuration or redirect problem and provide a retry path.

A development diagnostic may record which fields were present without logging sensitive values.

Example:

```text
[veyra] github setup callback {
  pathname: "/client/github/callback",
  installation_id_present: true,
  installation_id_numeric: true,
  setup_action: "install",
  state_present: true,
  state_recovered_from_session: false,
  code_present: false,
  query_keys: ["installation_id", "setup_action", "state"]
}
```

The diagnostic should log **presence and shape**, not the actual value of:

- `state`;
- `code`;
- access tokens;
- private credentials.

---

# Common causes of an empty callback

## Setup URL is missing

The GitHub App may not know where to return the user after installation.

Verify that the App's Setup URL points to:

```text
/client/github/callback
```

on the correct frontend origin.

---

## Setup URL points to the wrong environment

For example:

```text
localhost
```

while testing production, or a stale temporary deployment hostname after final cutover.

Update the GitHub App configuration to match the actual judge-facing frontend.

---

## GITHUB_APP_SLUG is missing

Without the slug, the generated installation URL cannot point to the actual GitHub App.

Verify the backend environment.

---

## Installation was started outside Veyra

If the user begins installation directly from GitHub instead of using Veyra's Connect GitHub flow, Veyra may not have issued the signed state required to bind the callback to the signed-in user.

Start the installation from:

```text
/client/github
```

---

## User authorization callback used instead of Setup URL

An OAuth callback can return:

```text
code
```

without producing the installation semantics Veyra needs.

Configure the GitHub App **Setup URL**, not only the user authorization callback.

---

# Organization approval pending

For organizations that require administrator approval, GitHub may return:

```text
setup_action=request
```

without:

```text
installation_id
```

This should not be treated as a successful completed installation.

Veyra should present a pending-approval state and allow the client to retry or refresh after the organization approves the GitHub App.

---

# Repository access updates

A user can later change which repositories the GitHub App installation can access.

When GitHub returns:

```text
setup_action=update
```

with an installation ID, Veyra can resynchronize the approved repository scope.

The backend should continue to treat GitHub as authoritative for which repositories belong to that installation.

---

# Installation tokens

The long-lived GitHub App private key is used by the backend to authenticate as the App.

Veyra then obtains installation-scoped access for the approved installation.

That access should remain:

- server-side;
- installation-scoped;
- temporary where supported by GitHub;
- absent from frontend JavaScript.

The browser does not need the GitHub installation token.

---

# Repository selection

After a successful installation, Veyra should only offer repositories available through that installation.

The normal job path becomes:

```text
GitHub App Installation
      ↓
Approved Repositories
      ↓
Select Repository
      ↓
Select Issue
      ↓
Create Job
```

A repository outside the approved GitHub App installation should not become usable merely because the browser sends its name to the API.

---

# GitHub and the autonomous runtime

The GitHub App integration is also a security boundary for autonomous execution.

The client authorizes repository access.

Veyra then coordinates the coding runtime against that approved repository.

The resulting software evidence includes real GitHub artifacts such as:

- repository;
- branch;
- commit;
- pull request;
- exact head SHA;
- Check Runs when required.

The Agent Starter does not get unrestricted access to every repository owned by the user.

---

# Pull request proof

A successful Veyra execution should produce a real GitHub pull request when the funded task requires code changes.

The PR provides externally visible evidence of:

- branch creation;
- code modifications;
- commit;
- exact implementation;
- reviewable diff.

Independent verification is tied to the exact submitted result rather than to a generic claim that "the PR exists."

---

# GitHub CI behavior

Veyra validation and independent verification are always required.

GitHub CI is client-selectable per funded job.

If the funded job contains:

```text
requireGithubChecks = true
```

the required Check Runs must pass against the exact submitted commit.

If GitHub CI is not a funded requirement, the absence of Check Runs does not block settlement by itself.

The coding agent is also prevented from modifying:

```text
.github/workflows/
```

during normal funded execution.

This prevents the agent from weakening or rewriting the CI policy merely to make its own submission pass.

---

# Webhook security

The webhook endpoint should verify GitHub signatures using:

```text
GITHUB_WEBHOOK_SECRET
```

Do not process a webhook as trusted solely because it reached the correct URL.

Webhook validation should occur before trusted state transitions.

Do not log the webhook secret.

---

# Production deployment

The final intended public configuration is:

```text
Frontend:
https://veyra.surf

Backend:
https://api.veyra.surf

GitHub Setup URL:
https://veyra.surf/client/github/callback

GitHub Webhook URL:
https://api.veyra.surf/api/v1/client/github/app/webhook/
```

During initial VPS deployment, a temporary HTTPS backend hostname may be used before `api.veyra.surf` is connected.

When switching from the temporary endpoint to the final domain:

1. update backend environment configuration;
2. update CORS/CSRF configuration as required;
3. update frontend API configuration;
4. update GitHub webhook URL if it changed;
5. verify the Setup URL still points to the correct frontend;
6. test a fresh installation round trip.

---

# Local development

Frontend:

```text
http://localhost:3000
```

Backend:

```text
http://localhost:8000
```

Local Setup URL:

```text
http://localhost:3000/client/github/callback
```

For GitHub webhooks, use a temporary HTTPS tunnel or equivalent development ingress pointing to the Django webhook endpoint.

Do not require a public tunnel for the ordinary browser Setup URL when the browser itself can return to localhost.

---

# Production verification checklist

Before the final judge-facing demo, verify:

```text
[ ] GITHUB_APP_ID configured
[ ] GITHUB_APP_SLUG configured
[ ] App private key configured server-side
[ ] GITHUB_WEBHOOK_SECRET configured
[ ] Setup URL points to the current frontend
[ ] Redirect on update enabled
[ ] Webhook URL points to the current HTTPS backend
[ ] GitHub App installation succeeds
[ ] installation_id returns to Veyra
[ ] signed state validates
[ ] approved repositories synchronize
[ ] repository issues load
[ ] Create Job can use an approved repository
[ ] runtime can create a real branch / commit / PR
[ ] exact submitted SHA is recorded
[ ] GitHub Checks behavior matches funded CI policy
```

---

# Judge-facing proof

During the final Veyra demo, the GitHub integration should make several facts visible.

## Before execution

Show:

- a real GitHub issue;
- the connected repository;
- the Veyra job created from that issue.

## During execution

Show:

- automatic assignment;
- runtime progress.

## After execution

Open the real GitHub pull request and show:

- changed files;
- branch;
- commit;
- PR number;
- exact head SHA where useful.

Then return to Veyra and show the independent verifier evaluating that same submitted result.

This demonstrates that GitHub is not being used as a decorative integration.

It is the actual software-delivery surface of the Veyra economy.

---

# Security boundaries

| Boundary | Rule |
| --- | --- |
| Browser vs App credentials | Private GitHub App credentials remain server-side |
| OAuth `code` vs installation | OAuth code is never treated as `installation_id` |
| Callback vs signed-in user | Signed state binds the round trip to the Veyra user |
| User repository list vs GitHub installation | Only installation-approved repositories are trusted |
| Browser URL vs installation URL | Frontend accepts only the expected GitHub App installation shape |
| Webhook request vs trusted event | Signature must verify |
| Coding agent vs workflows | `.github/workflows/` remains protected |
| PR existence vs verified result | Exact submitted artifact is independently verified |

---

# Files to inspect

## GitHub App integration

```text
backend/jobs/github_app.py
backend/jobs/github_views.py
backend/jobs/urls.py
```

## GitHub-related tests

```text
backend/jobs/test_github_app.py
backend/jobs/tests.py
```

## Frontend connection flow

```text
frontend/src/app/client/github/
frontend/src/components/jobs/github-app-connection.tsx
frontend/src/lib/github-install.ts
```

## Job creation and issue selection

```text
frontend/src/app/client/jobs/new/
backend/jobs/
```

---

# Troubleshooting order

If GitHub connection fails, check in this order:

```text
1. Is GITHUB_APP_SLUG correct?
2. Does install/start return a real /installations/new URL?
3. Is the GitHub App Setup URL correct?
4. Did the flow start from Veyra?
5. Did the callback receive installation_id?
6. Did the callback receive state?
7. Does Django accept the signed state?
8. Does the installation belong to the expected App?
9. Can Django mint installation access?
10. Do approved repositories synchronize?
```

This sequence usually isolates whether the failure is:

- configuration;
- browser round trip;
- state validation;
- App authentication;
- repository synchronization.

---

# Final integration principle

Veyra's GitHub integration is designed around one rule:

> **The client chooses repository access through a GitHub App installation, while Veyra uses that scoped installation to coordinate real autonomous software work.**

The installation authorizes the repository.

The issue defines the work.

The Agent Starter produces the implementation.

The pull request proves the software artifact exists.

The verifier checks the exact result.

Arc settles the economic outcome.

That is the full Veyra loop:

**GitHub issue → funded job → autonomous PR → independent verification → USDC settlement.**
