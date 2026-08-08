# Veyra Deployment Guide

## Deployment goal

The production Veyra deployment should preserve the same end-to-end architecture that has already been validated locally while separating public web traffic from private autonomous runtime infrastructure.

The intended judge-facing layout is:

```text
                         Public Internet
                               │
                  ┌────────────┴────────────┐
                  │                         │
                  ▼                         ▼
             veyra.surf                HTTPS API
          Next.js Frontend             Django on VPS
           hosted on Vercel                 │
                                            ▼
                              ───── Private VPS Boundary ─────
                                            │
                   ┌────────────────────────┼────────────────────────┐
                   │                        │                        │
                   ▼                        ▼                        ▼
              PostgreSQL            Execution Controller       Agent Starter
                                                                    │
                                                                    ▼
                                                             Isolated Workspaces
                                            │
                                            ▼
                                   Independent Verifier
                              ──────────────────────────────────────
                                            │
                           ┌────────────────┴────────────────┐
                           │                                 │
                           ▼                                 ▼
                        GitHub                           Arc + Circle
```

The core rule is simple:

> **Expose the frontend and backend API. Keep the database, execution controller, Agent Starter, and verifier private.**

---

# Target deployment

## Public

### Frontend

```text
https://veyra.surf
```

Recommended host:

```text
Vercel
```

### Backend API

Final target:

```text
https://api.veyra.surf
```

During initial VPS deployment and testing, Veyra may use a temporary SSL-enabled hostname such as an `sslip.io` address that resolves directly to the VPS.

That temporary hostname should be treated as a deployment-validation endpoint, not the final product brand URL.

---

# Private VPS services

The following services should not be exposed directly to the public internet:

- PostgreSQL;
- execution controller;
- Agent Starter;
- independent verifier.

Example internal service layout:

```text
Django/Gunicorn        127.0.0.1:8000
Agent Starter          127.0.0.1:9300
Verifier               127.0.0.1:9200
PostgreSQL             127.0.0.1:5432
Execution Controller   no listening port
```

A reverse proxy such as Nginx or Caddy should expose only the backend HTTPS interface.

---

# Repository deployment map

| Repository path | Production target |
| --- | --- |
| `frontend/` | Vercel |
| `backend/` | VPS |
| `agent-starter/` | VPS default hosted runtime; optional external owner hosts |
| `verifier/` | VPS or independently operated verifier host |
| `smart-contracts/` | Already deployed to Arc Testnet |
| `deploy/` | Deployment configuration and operational material |
| `docs/` | Documentation only |
| `scripts/` | Local/operational tooling |

---

# Arc deployment used by production

| Component | Value |
| --- | --- |
| Network | Arc Testnet |
| Chain ID | `5042002` |
| Contract | `VeyraJobEscrow` |
| Escrow Address | `0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5` |
| Arc Testnet USDC | `0x3600000000000000000000000000000000000000` |

The deployed contract source is in:

```text
smart-contracts/contracts/VeyraJobEscrow.sol
```

The deployment record is in:

```text
smart-contracts/deployments/arc-testnet.json
```

Do not redeploy or change the production contract address as part of ordinary application deployment.

---

# Recommended deployment sequence

Deploy in this order:

```text
1. Provision VPS
2. Install PostgreSQL
3. Deploy repository
4. Configure backend environment
5. Apply Django migrations
6. Start Django/Gunicorn
7. Start execution controller
8. Start Agent Starter
9. Start verifier
10. Configure reverse proxy + HTTPS
11. Validate backend health through temporary HTTPS hostname
12. Deploy frontend to Vercel
13. Point frontend to production API
14. Configure final CORS/CSRF/cookies
15. Connect api.veyra.surf
16. Run production health checks
17. Run one fresh end-to-end job
18. Record production proof
```

Do not start with the final live job before the production services are healthy.

---

# VPS requirements

A Linux VPS should provide enough resources to run:

- Django/Gunicorn;
- PostgreSQL;
- execution controller;
- one Veyra-hosted Agent Starter;
- one verifier;
- temporary agent workspaces;
- package/tool execution used by supported repositories.

Recommended base operating system:

```text
Ubuntu LTS
```

Recommended software:

- Python 3.12;
- PostgreSQL;
- Git;
- Node.js/npm;
- Nginx or Caddy;
- systemd;
- any language/toolchain required by the demo repository.

Because the Agent Starter supports multiple ecosystems, the final VPS may also need selected project runtimes such as:

- Rust/Cargo;
- Go;
- Java/Maven/Gradle;
- PHP;
- Ruby;
- Foundry;
- Hardhat.

Only install what is needed for the intended production/demo workload.

---

# Production users and service separation

Do not run every Veyra process as root.

Use separate service accounts where practical.

Example:

```text
veyra-web
veyra-agent
veyra-verifier
```

At minimum:

- Django should run as a non-root service user;
- Agent Starter should run as a non-root service user;
- verifier should run as a separate non-root service user;
- PostgreSQL should use its native service account.

Separate service users help isolate:

- model-provider credentials;
- runtime identities;
- temporary workspaces;
- logs;
- signing material.

---

# Repository location

Use a stable deployment path, for example:

```text
/opt/veyra
```

or:

```text
/srv/veyra
```

Example:

```bash
sudo mkdir -p /opt/veyra
sudo chown <deploy-user>:<deploy-user> /opt/veyra
```

The application should not depend on a machine-specific folder name.

The repository resolves paths relative to the project and does not depend on a machine-specific repository folder name.

---

# Backend environment

Create the production backend environment from:

```text
backend/.env.example
```

Store the real production file only on the host.

Never commit it.

Production values should cover the categories already expected by the application, including:

- Django secret/configuration;
- database;
- frontend/API origins;
- Circle;
- GitHub App;
- Arc RPC;
- escrow contract;
- contract-authority signer;
- agent runtime;
- verifier;
- model-provider configuration.

Do not copy local development values blindly.

---

# Django production settings

Production Django configuration should include secure values appropriate to HTTPS deployment.

Review settings such as:

```text
DEBUG
SECRET_KEY
ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS
CORS_ALLOWED_ORIGINS
SESSION_COOKIE_SECURE
CSRF_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER
```

Expected public origins after final domain setup:

```text
https://veyra.surf
https://api.veyra.surf
```

If a temporary `sslip.io` API hostname is used during deployment validation, add only that exact HTTPS origin as needed for the temporary phase.

Remove obsolete temporary origins after final cutover.

---

# PostgreSQL

Use PostgreSQL as the production database.

Do not expose port `5432` publicly.

Recommended network binding:

```text
127.0.0.1
```

or a private network interface when the database is on a separate private host.

Create a dedicated database and user for Veyra.

Example structure:

```text
database: veyra
user:     veyra_app
```

Use a strong password stored only in the host-managed environment.

---

# Database migrations

Before starting the production web service:

```bash
cd /opt/veyra/backend
../.venv/bin/python manage.py migrate
```

Then run:

```bash
../.venv/bin/python manage.py check
```

Do not generate new migrations on the VPS as a substitute for fixing source-controlled model drift.

Production deployment should apply committed migrations.

---

# Python environment

Create a dedicated virtual environment:

```bash
cd /opt/veyra
python3.12 -m venv .venv
```

Install backend dependencies:

```bash
.venv/bin/pip install -r backend/requirements.txt
```

Install Agent Starter dependencies:

```bash
.venv/bin/pip install -r agent-starter/requirements.txt
```

Install verifier dependencies according to the verifier package configuration already present in the repository.

Avoid ad hoc dependency upgrades during deployment.

---

# Django web process

Run Django behind a production WSGI server.

Use the Gunicorn configuration/command already aligned with the repository, including the command referenced by:

```text
backend/Dockerfile
```

Bind Gunicorn privately, for example:

```text
127.0.0.1:8000
```

Do not expose Gunicorn directly to the internet.

The reverse proxy should be the only public entry point.

---

# Reverse proxy

Use Nginx or Caddy in front of Django.

Responsibilities:

- terminate TLS;
- expose the public backend hostname;
- proxy requests to `127.0.0.1:8000`;
- forward scheme/host information correctly;
- enforce reasonable request/body/time limits;
- keep internal runtime ports private.

Conceptual Nginx shape:

```nginx
server {
    listen 443 ssl;
    server_name api.veyra.surf;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Use real certificate paths and hardened TLS configuration appropriate to the host.

---

# Temporary sslip.io deployment endpoint

For fast VPS validation, the backend can initially be exposed through an `sslip.io` hostname that resolves to the VPS IP.

Example shape:

```text
https://api.<VPS-IP-WITH-DASHES>.sslip.io
```

The exact hostname depends on the VPS IP and chosen certificate/reverse-proxy setup.

Use the temporary hostname to validate:

- HTTPS;
- Django routing;
- login callbacks;
- CORS;
- CSRF;
- frontend-to-backend requests;
- Circle callbacks/flows where applicable;
- GitHub callback configuration where applicable.

Once the final domain is ready, migrate the frontend API configuration to:

```text
https://api.veyra.surf
```

and remove unnecessary temporary origins.

---

# Frontend deployment on Vercel

Set the Vercel project root to:

```text
frontend
```

Use the repository's locked dependencies.

Typical deployment flow:

```text
Install: npm ci
Build:   npm run build
```

Production environment variables should include the public values expected by the frontend, such as:

```text
NEXT_PUBLIC_VEYRA_API_URL
NEXT_PUBLIC_CIRCLE_APP_ID
NEXT_PUBLIC_GOOGLE_CLIENT_ID
Arc explorer base URL variable used by the application
```

Do not place server-only secrets in `NEXT_PUBLIC_*` variables.

Every `NEXT_PUBLIC_*` value is exposed to the browser.

---

# Frontend API configuration

During temporary VPS validation:

```text
NEXT_PUBLIC_VEYRA_API_URL=https://<temporary-ssl-host>
```

After final domain cutover:

```text
NEXT_PUBLIC_VEYRA_API_URL=https://api.veyra.surf
```

Redeploy the frontend after changing public environment variables.

---

# Google authentication

Production Google OAuth settings must align with the final frontend/backend routes used by Veyra.

Verify:

- authorized JavaScript origins;
- redirect URIs;
- frontend origin;
- backend callback/redirect behavior.

Do not leave production authentication dependent on `localhost`.

---

# GitHub App production configuration

Verify the GitHub App configuration against the production deployment.

Review:

- callback URL;
- setup URL if used;
- webhook URL if used;
- homepage URL;
- required permissions;
- repository installation access.

Do not change application permissions during the final hackathon deployment unless the current proven flow requires it.

A production callback must point to the actual deployed Veyra route, not a stale local URL.

---

# Circle production/testnet configuration

Veyra uses Circle wallet infrastructure in distinct roles.

Client funding uses the supported user-controlled wallet flow.

Agent economic activity uses dedicated developer-controlled wallets.

Backend production configuration must preserve the exact wallet behavior already validated by the application.

Do not expose Circle credentials in the frontend unless they are explicitly public client identifiers expected by the browser SDK.

Server credentials remain on the VPS.

---

# Execution controller

Run exactly one active execution controller per intended database lease domain.

The controller is not a web service.

It does not need a public port.

Its responsibilities include:

- funded job discovery;
- automatic matching;
- assignment reservation;
- claim coordination;
- execution progression;
- retry handling;
- verification dispatch;
- settlement reconciliation;
- recovery.

Run it under a process supervisor such as systemd.

Do not run duplicate unmanaged copies during production testing.

---

# Agent Starter

The default production experience uses a Veyra-hosted Agent Starter runtime.

Recommended binding:

```text
127.0.0.1:9300
```

The runtime should use its own:

- environment file;
- runtime identity;
- provider credentials;
- temporary workspace root;
- logs.

Its provider secret should never be readable by the frontend.

The runtime should communicate only with the Veyra control plane as required.

---

# Independent verifier

Run the verifier as a distinct process and identity.

Recommended binding:

```text
127.0.0.1:9200
```

The verifier should use:

- a distinct runtime identity;
- a separate provider configuration;
- a separate environment file;
- separate logs;
- read-only repository access for verification work where the architecture requires it.

The verifier should not share the coding agent's identity.

The verifier should not directly hold the settlement-authority key.

---

# Contract authority

The current Arc Testnet contract requires configured authority for owner-only settlement operations.

That signer belongs to the backend's settlement boundary, not the coding model or verifier.

For a hackathon VPS, protect the key as a server-only secret with strict file permissions.

For a hardened production environment, prefer managed signing infrastructure such as:

- KMS;
- HSM;
- managed key custody.

Never expose the signer to:

- browser JavaScript;
- Agent Starter;
- verifier;
- GitHub repository content.

---

# systemd process model

Recommended service set:

```text
veyra-web.service
veyra-controller.service
veyra-agent.service
veyra-verifier.service
```

PostgreSQL runs through its own system service.

A service should have:

- explicit working directory;
- explicit environment file;
- non-root user;
- restart policy;
- log output;
- dependency ordering where needed.

Conceptual shape:

```ini
[Unit]
Description=Veyra Web
After=network.target postgresql.service

[Service]
User=veyra-web
WorkingDirectory=/opt/veyra/backend
EnvironmentFile=/etc/veyra/backend.env
ExecStart=/opt/veyra/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Adapt the exact `ExecStart` command to the repository's actual Django/Gunicorn configuration.

---

# Service isolation

Recommended host-managed environment files:

```text
/etc/veyra/backend.env
/etc/veyra/agent.env
/etc/veyra/verifier.env
```

Permissions should restrict access to the service user/root.

Do not place production `.env` files in a world-readable directory.

Do not commit them.

---

# Firewall

Expose only the ports that need to be public.

Typical public ports:

```text
22   SSH
80   HTTP redirect / certificate flow
443  HTTPS
```

Keep private:

```text
5432 PostgreSQL
8000 Gunicorn
9200 Verifier
9300 Agent Starter
```

If SSH is not required from the entire internet, restrict it to trusted addresses where practical.

---

# Workspace storage

Agent workspaces should live outside public web roots.

Example:

```text
/var/lib/veyra/workspaces
```

Use:

- dedicated ownership;
- restrictive permissions;
- cleanup policies;
- sufficient disk space.

Do not point autonomous workspaces at:

```text
/etc
/root
/home/<unrelated-user>
/opt/veyra/.git
```

The runtime should continue to use its existing isolated workspace controls.

---

# Logging

Keep separate logs for:

- web/backend;
- execution controller;
- Agent Starter;
- verifier;
- reverse proxy.

Avoid logging:

- API keys;
- private keys;
- Authorization headers;
- full database connection strings;
- wallet signing material;
- model-provider credentials.

Use journald/systemd logging or host-managed rotated log files.

---

# Health checks

## Public backend

After reverse proxy configuration:

```bash
curl -fsS https://api.veyra.surf/api/health/
```

During temporary hostname validation:

```bash
curl -fsS https://<temporary-ssl-host>/api/health/
```

## Internal Agent Starter

From the VPS:

```bash
curl -fsS http://127.0.0.1:9300/veyra/health
```

## Internal verifier

From the VPS:

```bash
curl -fsS http://127.0.0.1:9200/veyra/health
```

## PostgreSQL

Verify the application can connect using the configured production database credentials.

Do not expose a database health endpoint publicly.

---

# Deployment validation checklist

Before connecting the frontend:

```text
[ ] PostgreSQL running
[ ] migrations applied
[ ] Django system check passes
[ ] Gunicorn running
[ ] backend health returns success
[ ] exactly one execution controller running
[ ] Agent Starter healthy
[ ] verifier healthy
[ ] Arc RPC configuration valid
[ ] contract address correct
[ ] Circle configuration valid
[ ] GitHub configuration valid
[ ] reverse proxy working
[ ] HTTPS certificate valid
```

Then connect the frontend and verify:

```text
[ ] veyra.surf loads
[ ] frontend API calls reach VPS
[ ] login works
[ ] cookies/session behavior works
[ ] CORS is correct
[ ] CSRF is correct
[ ] GitHub connection works
[ ] Create Job works
[ ] Review & Fund works
[ ] Agent Owner screens work
```

---

# CORS, CSRF, and cookies

Production frontend/backend separation means these settings matter.

The final trusted frontend origin should be:

```text
https://veyra.surf
```

The backend origin should be:

```text
https://api.veyra.surf
```

Credentialed requests require the backend to use the correct combination of:

- CORS allowed origins;
- CSRF trusted origins;
- secure session cookies;
- secure CSRF cookies;
- proxy HTTPS awareness;
- SameSite configuration appropriate to the final architecture.

Do not use wildcard credentialed CORS in production.

---

# Final production regression

After deployment, run the health checks first.

Then run one fresh real job.

The production proof must be:

```text
New GitHub Issue
      ↓
New Veyra Job
      ↓
USDC Funding on Arc
      ↓
Automatic Agent Matching
      ↓
Autonomous Execution
      ↓
Real Commit
      ↓
Real Pull Request
      ↓
Independent Verification
      ↓
Verification Evidence
      ↓
Arc Settlement
      ↓
USDC Released to Agent
      ↓
COMPLETED
```

Do not use:

- manual database advancement;
- manual assignment;
- manual claim;
- fabricated PRs;
- fabricated verification;
- fabricated settlement.

---

# Evidence to record after deployment

Capture:

| Evidence | Value |
| --- | --- |
| Frontend URL | `https://veyra.surf` after final cutover |
| Backend API | `https://api.veyra.surf` after final cutover |
| GitHub Issue | |
| Veyra Job ID | |
| Arc Job ID | |
| Assigned Agent | |
| Agent Wallet | |
| Pull Request | |
| Commit SHA | |
| Verification Verdict | |
| Verification Report Hash | |
| Evidence Hash | |
| Settlement Transaction | |
| Final State | `COMPLETED` |

Then update:

```text
README.md
JUDGES.md
docs/ARC_INTEGRATION.md
docs/DEMO.md
```

with the genuine production evidence.

---

# Rollback strategy

Deployment should be reversible.

Before replacing a working VPS release:

1. preserve the previous source checkout or release directory;
2. back up PostgreSQL using an appropriate database backup method;
3. preserve host-managed environment files;
4. record the currently running commit;
5. deploy the new release;
6. apply only committed migrations;
7. restart services;
8. run health checks.

If the new release fails before economic activity begins, restore the previous application release and restart services.

Do not roll back onchain state.

Arc transactions that have already finalized remain authoritative.

Any interrupted offchain workflow should be reconciled against chain state before attempting a new economic transaction.

---

# Secret handling

Never commit:

```text
.env
*.pem
*.key
private keys
mnemonics
Circle secrets
GitHub App private keys
model-provider credentials
database passwords
contract-authority signing keys
runtime private identities
```

The repository should contain only safe `.env.example` templates.

Production values belong in the host's secret-management boundary.

---

# Do not expose runtime dashboards

The Agent Starter and verifier health/runtime ports are implementation details.

Do not publish:

```text
https://agent.veyra.surf
https://verifier.veyra.surf
```

unless a future product requirement explicitly needs a hardened authenticated public runtime interface.

For the current production architecture, keep them private.

---

# Owner-hosted Agent Starter

External agent owners may operate their own Agent Starter as an optional advanced mode.

That deployment is separate from the Veyra-hosted judge-facing runtime.

An external owner is responsible for their own:

- model provider;
- API key;
- runtime host;
- signing identity;
- workspace;
- uptime.

The Veyra-hosted runtime remains the default product experience.

---

# Deployment success criteria

A production deployment is ready for judging when:

```text
[ ] veyra.surf loads over HTTPS
[ ] backend API is reachable over HTTPS
[ ] PostgreSQL is private and healthy
[ ] exactly one execution controller is active
[ ] Agent Starter is private and healthy
[ ] verifier is private and healthy
[ ] GitHub integration works
[ ] Circle wallet flow works
[ ] Arc RPC works
[ ] deployed contract configuration matches repository
[ ] a fresh funded job completes end-to-end
[ ] real PR exists
[ ] independent verification succeeds
[ ] real Arc settlement exists
[ ] agent payment is visible
[ ] final state is COMPLETED
```

At that point the deployment has proven the full Veyra economy:

> **Fund → Match → Execute → Verify → Settle → Reputation**
