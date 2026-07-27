# Worker Circle Wallet

This onboarding step provisions one Circle developer-controlled smart-contract
account for the Veyra Code Agent.

## Fixed configuration

- Blockchain: `ARC-TESTNET`
- Account type: `SCA`
- Custody: developer controlled
- Wallet-set name: `Veyra Worker Agents`

## Secret boundary

The Circle API key and entity secret remain in the backend runtime environment.
Only the following public metadata is stored on `WorkerAgent`:

- Circle wallet-set ID
- Circle wallet ID
- wallet address
- blockchain
- account type

## Command

```powershell
python manage.py create_worker_wallet
```

The command is idempotent after a wallet has been attached to the worker. It
will print the existing wallet instead of creating another one.
