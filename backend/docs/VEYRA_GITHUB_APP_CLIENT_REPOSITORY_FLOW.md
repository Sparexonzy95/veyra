# Veyra GitHub App: Client Repository Flow

Version: Phase 1 client repository integration

## Product decision

Veyra uses one platform GitHub App.

Agent owners do not connect a personal GitHub account during agent onboarding. Their hosted agents receive repository access only for the client job currently assigned to them.

Clients install the Veyra GitHub App while creating a GitHub-backed job and select the exact repositories Veyra may access.

## User flow

```text
Client opens Create Job
→ Connect GitHub
→ GitHub installation screen opens
→ Client selects a personal account or organisation
→ Client approves selected repositories
→ GitHub returns to Veyra
→ Veyra stores the installation and approved repository IDs
→ Client loads an issue from an approved repository
→ Client reviews, funds, and publishes the job
```

The client repeats the installation only when adding another GitHub account, organisation, or repository that is not already approved.

## Paid-job execution

```text
Job is assigned
→ Veyra confirms the repository installation is healthy
→ Veyra signs a GitHub App JWT on the backend
→ GitHub returns a short-lived installation token scoped to one repository
→ Veyra-hosted runtime clones the repository
→ Agent changes code and runs validation
→ Veyra pushes a job branch to the approved repository
→ Veyra opens a pull request
→ The short-lived token expires
```

Installation tokens are not saved in PostgreSQL and are never sent to the AI model. The GitHub App private key and webhook secret remain server-side.

## Required GitHub App repository permissions

- Metadata: Read-only, provided by GitHub
- Contents: Read and write
- Issues: Read-only
- Pull requests: Read and write
- Checks: Read-only

Veyra currently handles these webhook events:

- Installation created, deleted, suspended, and unsuspended
- Installation repositories added or removed
- New installation permissions accepted

## GitHub App setup values

Development setup URL:

```text
http://localhost:3000/dashboard/github/callback
```

Production setup URL:

```text
https://<VEYRA-FRONTEND-DOMAIN>/dashboard/github/callback
```

Backend webhook URL:

```text
https://<VEYRA-BACKEND-DOMAIN>/api/v1/webhooks/github/
```

GitHub cannot deliver webhooks directly to localhost. During local development, installation and manual refresh work through the browser callback. Live webhook testing requires a secure tunnel or a deployed backend.

## Backend environment

Use the downloaded GitHub App `.pem` file outside the repository whenever possible.

```ini
GITHUB_APP_ID=
GITHUB_APP_SLUG=
GITHUB_APP_PRIVATE_KEY_PATH=C:\\secure\\veyra-github-app.pem
GITHUB_WEBHOOK_SECRET=
GITHUB_APP_INSTALL_URL=
GITHUB_APP_TIMEOUT_SECONDS=20
GITHUB_APP_STATE_TTL_SECONDS=900
VEYRA_FRONTEND_URL=http://localhost:3000
```

`GITHUB_APP_PRIVATE_KEY` remains available for hosting platforms that inject multiline secrets. Do not configure both unless necessary.

## Stored records

`GitHubAppInstallation` stores:

- Veyra client owner
- GitHub installation ID
- GitHub account or organisation
- repository-selection mode
- installation permissions
- health state
- suspension and last-check information

`GitHubRepositoryAccess` stores:

- GitHub repository ID
- owner and repository name
- private/public status
- default branch
- active access state
- parent installation

`JobDraft.github_repository_access` binds each job to one exact approved repository.

## Health states

- `CONNECTED`
- `CHECKING`
- `LIMITED_ACCESS`
- `CREDENTIAL_GENERATION_FAILED`
- `SUSPENDED`
- `RECONNECT_REQUIRED`
- `DISCONNECTED`

No healthy repository installation means:

```text
No issue preview
No job review
No funding challenge
No new claim
No code execution
```

## Legacy qualification identity

The existing Veyra-controlled GitHub identity remains only for the internal controlled qualification repository. It is not used for paid client repositories. Paid jobs use repository-scoped GitHub App installation tokens.
