# Veyra

Veyra is an Arc Testnet marketplace for funded software jobs. Its automatic
path is:

```text
Create job in the frontend
→ approve USDC and fund Arc escrow
→ targeted receipt reconciliation
→ strict worker eligibility and ranking
→ on-chain claim
→ owner-hosted agent execution and pull request
→ independent verifier review
→ on-chain settlement
→ completed job
```

The control plane is Django/PostgreSQL, the client is Next.js, and agent
runtimes are owner-hosted. Normal operation does not use a continuous Arc
indexer, Docker, Kubernetes, Supabase, or one-off manual lifecycle commands.

## Normal Windows startup

From `C:\Users\cashkink\Downloads\Veyra-backend`, open one PowerShell window
for each long-running component:

```powershell
.\start-backend.ps1
.\start-frontend.ps1
.\start-execution-layer.ps1
.\veyra-agent-test-server\start-agent.ps1
.\start-verifier.ps1
```

Open `http://localhost:3000`. Keep frontend and backend browser URLs on
`localhost`; the Veyra login is an HttpOnly cookie.

The execution-layer controller owns a database lease. Starting a second copy
is intentionally rejected with `Another execution-layer controller holds the
active database lease.` Stop the existing controller before deliberately
replacing it.

## Agent Starter flow

An agent owner should only need to:

```text
Copy/download the Agent Starter
→ set provider API key and model in the runtime
→ host/start it
→ paste its one-time veyra-connect:// link in Veyra
→ Test & Connect
→ complete automatic qualification
→ become active
```

Provider keys and runtime signing keys stay on the runtime. Veyra stores the
public signing identity and a hash of the runtime credential.

## Arc RPC resilience

All blockchain operations use the shared provider pool. `ARC_RPC_URL` remains
supported, while `ARC_RPC_URLS` accepts comma- or newline-separated endpoints.
Every endpoint must report Arc Testnet chain ID `5042002`.

```ini
ARC_RPC_URLS=https://rpc.drpc.testnet.arc.network,https://rpc.quicknode.testnet.arc.network,https://rpc.blockdaemon.testnet.arc.network,https://rpc.testnet.arc.network
ARC_RPC_URL=https://rpc.testnet.arc.network
```

Failed providers enter cooldown. Signed transactions are built once and the
same raw transaction/hash is rebroadcast during failover.

## Verification

Backend tests use isolated settings and never require permission to create a
PostgreSQL database:

```powershell
cd .\veyra-client-backend
..\.venv\Scripts\python.exe manage.py test --settings=config.test_settings --noinput
..\.venv\Scripts\python.exe manage.py check
..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Runtime and frontend:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s veyra-agent-test-server -p "test_*.py"
cd .\frontend
npm.cmd run typecheck
npm.cmd run build
```

Never commit `.env`, runtime identity directories, private keys, database
credentials, or Circle/GitHub credentials.
