# Veyra Runner — Phase 1 Step 2

Veyra Runner securely connects an owner-hosted coding agent environment to the Veyra control plane.

This first runner build implements:

- one-time pairing codes;
- one device keypair generated locally;
- signed heartbeat requests;
- one Runner hosting multiple Veyra agents;
- safe environment detection;
- no GitHub, Circle, Arc, or model credentials sent to Veyra.

The Runner device key is an authentication key only. It is not an Arc wallet and must never receive funds.

## Local development setup

```powershell
cd C:\Users\cashkink\Downloads\Veyra-backend\veyra-runner
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Generate a pairing code from the agent dashboard, then run:

```powershell
python runner.py pair --server http://localhost:8000 --name "Maryam Development Runner"
```

The command asks for the code privately so it is not saved in shell history.

Send the first heartbeat:

```powershell
python runner.py start --once
```

Keep the development Runner online:

```powershell
python runner.py start
```

Local identity files are stored under `%USERPROFILE%\.veyra\` and must never be committed or shared.
