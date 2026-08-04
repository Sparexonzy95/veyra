# Veyra Agent Starter

This is the owner-hosted runtime distributed to external agent owners and used
for one VPS demo agent. The owner supplies and pays for the model provider. The
provider API key and runtime Ed25519 private key remain on the owner's host.

The runtime receives narrowly scoped assignments, creates disposable
workspaces outside its identity directory, asks the configured model to perform
the task, runs the supplied tests, and signs its result for Veyra. Automatic
qualification uses a safe synthetic task before an agent becomes active.

## Setup

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r agent-starter\requirements.txt
Copy-Item agent-starter\.env.example agent-starter\.env
```

Set `AI_PROVIDER`, `AI_MODEL`, `AI_BASE_URL`, and `AI_API_KEY` in the local
`.env`, then start it:

```powershell
.\agent-starter\start-agent.ps1
```

The default dashboard is `http://127.0.0.1:9100`. On first start the runtime
creates an ignored `.veyra-runtime` directory and a short-lived
`veyra-connect://` link. Paste that link into Veyra's **Test & Connect** flow.
No Runner pairing code is used.

For a remotely hosted owner runtime, set the bind/public host and port values
for the owner's network topology and expose it only through authenticated TLS.
Do not commit `.env`, `.veyra-runtime`, workspaces, logs, or provider keys.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s agent-starter -p "test_*.py"
```
