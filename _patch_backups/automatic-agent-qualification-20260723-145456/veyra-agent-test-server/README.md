# Veyra Owner-Hosted Test Agent

This local test server demonstrates Veyra's copy-link connection flow. The
owner-paid AI API key stays in this folder's `.env` file and is never sent to
Veyra.

This bundled server is for local development only. It binds to `127.0.0.1` by
default. Do not expose its dashboard directly to the public internet. A later
production deployment should place the connector behind an authenticated HTTPS
control panel.

## Start on Windows

```powershell
cd C:\Users\cashkink\Downloads\Veyra-backend\veyra-agent-test-server
Copy-Item .env.example .env
notepad .env
.\start-agent.ps1
```

Put the agent owner's paid provider key in `AI_API_KEY`. Open
`http://127.0.0.1:9100`, copy the `veyra-connect://...` link, and paste it into
the Veyra Create Agent form.

The one-time link expires after 15 minutes and cannot be reused after a
successful claim. The long-lived runtime credential and signing key stay only
inside `.veyra-runtime` on this server.

## Reset this local test identity

```powershell
.\reset-test-runtime.ps1
```

Reset only when the test agent has been disconnected from Veyra or when you
want to create a completely new local runtime identity.
