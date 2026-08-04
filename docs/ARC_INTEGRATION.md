# Arc integration

Veyra uses Arc Testnet as its escrow and settlement layer and USDC as the job
currency.

## Configured deployment

| Setting | Value |
| --- | --- |
| Chain | Arc Testnet |
| Chain ID | `5042002` |
| VeyraJobEscrow | `0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5` |
| USDC | `0x3600000000000000000000000000000000000000` |
| USDC decimals | `6` |

The canonical defaults live in `backend/config/settings.py` and
`backend/.env.example`; the ABI is under `backend/blockchain/abi/`.

## Funding

Django builds the ERC-20 approval and escrow `createJob` calls. The frontend
passes those challenges to Circle's user-controlled wallet SDK but cannot
replace the target contract or calldata. After the challenge completes, the
frontend sends the Circle transaction ID to Django. Django fetches that exact
transaction and Arc receipt and checks the wallet sender, destination, calldata
hash, status, allowance or `JobCreated` event, and on-chain job ID.

This targeted receipt path is the normal funding mechanism; a continuously
running global event indexer is not required for it.

## Agent and settlement transactions

The execution controller prepares claims and submissions against the same
configured chain and contract. Signed raw transactions are built once; RPC
failover rebroadcasts the same envelope rather than creating a different
transaction. Every provider must report chain ID `5042002`.

The independent verifier does not hold the settlement key. Django validates the
verifier evidence, then uses the configured contract-authority signer for the
owner-only settlement operation required by the current contract. Production
operations should place that signer in KMS/HSM custody.
