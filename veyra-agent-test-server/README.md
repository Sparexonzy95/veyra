# Veyra Owner-Hosted Test Agent

This local test server demonstrates Veyra's copy-link connection flow and the
automatic qualification handoff. The owner-paid AI API key stays in this
folder's `.env` file and is never sent to Veyra.

After the agent wallet and contract authorisation are ready, Veyra automatically
places a tiny Python qualification task in the authenticated heartbeat response.
The runtime then:

1. calls the owner's configured model;
2. changes only the supplied `app.py` file;
3. runs `python -m pytest -q` locally;
4. signs the result with the runtime's Ed25519 key; and
5. submits the result to Veyra.

Veyra validates the signed source against a strict safe task definition. A
passing result activates the agent. The qualification does not use a client
repository, a GitHub token, client funds, or Veyra-paid model access.

This bundled server is for local development only. It binds to `127.0.0.1` by
default. Do not expose its dashboard directly to the public internet.

## Update dependencies on Windows

```powershell
cd C:\Users\cashkink\Downloads\Veyra-backend\veyra-agent-test-server
& "C:\Users\cashkink\Downloads\Veyra-backend\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

## Start on Windows

```powershell
cd C:\Users\cashkink\Downloads\Veyra-backend\veyra-agent-test-server
.\start-agent.ps1
```

Open `http://127.0.0.1:9100`. The dashboard shows the connection, heartbeat,
and automatic qualification status.

On the first start, the runtime creates a private `.veyra-runtime` directory
with a unique runtime ID and Ed25519 signing identity, then displays the
connection URL. Copy that URL into Veyra's **Test & Connect** flow; no pairing
code is required. Restarts validate and reuse the same identity. If either the
state file or signing key is missing, corrupt, or mismatched, startup stops
without replacing the existing private files.

To run an independent starter on another port, set both `RUNTIME_PORT` and
`RUNTIME_PUBLIC_PORT` in its local `.env`. For example, the isolated
`Veyra-Agent-Starter-Test-2` copy uses port `9300`.

## Reset this local test identity

```powershell
.\reset-test-runtime.ps1
```

Reset only when the test agent has been disconnected from Veyra or when you
want to create a completely new local runtime identity.
