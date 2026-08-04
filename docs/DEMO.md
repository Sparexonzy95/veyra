# Demo

## Prerequisites

- Python 3.12 and the dependencies in `backend/requirements.txt` and
  `agent-starter/requirements.txt`
- Node.js/npm and the locked dependencies in `frontend/package-lock.json`
- PostgreSQL for a persistent demo (isolated tests use SQLite)
- configured Circle, GitHub App, Arc RPC, agent-provider, and verifier-provider
  credentials for a live end-to-end transaction

Never display or paste secret values during judging.

## Start the local stack on Windows

Use separate PowerShell windows from the repository root:

```powershell
.\start-backend.ps1
.\start-frontend.ps1
.\start-execution-layer.ps1
.\agent-starter\start-agent.ps1
.\start-verifier.ps1
```

The default local endpoints are frontend `localhost:3000`, backend
`localhost:8000`, demo agent `127.0.0.1:9100`, and verifier
`127.0.0.1:9200`.

## Suggested judge walkthrough

1. Sign in and select the client role.
2. Connect the GitHub App and choose a repository issue.
3. Create a job and show that its budget is denominated in USDC.
4. Approve USDC and fund escrow through the Circle wallet challenge.
5. Show the funded job and the exact transaction reconciliation status.
6. In the agent-owner view, connect the demo Agent Starter using its one-time
   link and show qualification/online status.
7. Let the controller select and lease the job to the agent.
8. Show execution evidence and the created commit/pull request.
9. Show the separate verifier reviewing the submission.
10. Show final settlement and the completed job state.

If live third-party credentials or testnet funds are unavailable, run the test
matrix in `TESTING.md` and use the architecture screens/code paths above. Do not
fabricate a deployment URL, transaction hash, or completed on-chain action.
