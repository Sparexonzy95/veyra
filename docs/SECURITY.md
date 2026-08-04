# Security

## Secrets and identity

- `.env` files, private keys, runtime identities, databases, workspaces, logs,
  and generated output are ignored and must stay outside source control.
- Agent and verifier model keys stay on their respective runtime hosts.
- Runtime connection credentials are stored hashed by Django; Ed25519 private
  keys remain in each runtime's `.veyra-runtime` directory.
- Use separate model accounts and identities for worker and verifier roles.
- Move the current testnet contract-owner/verifier signer into KMS/HSM custody
  before production use.

## Request and transaction controls

- Django, not the browser, chooses protected contract addresses and calldata.
- Circle transaction reconciliation checks the exact recorded transaction and
  receipt rather than trusting a client-supplied hash alone.
- GitHub App tokens are installation/repository scoped and short-lived.
- Execution leases, signed runtime payloads, credential hashes, replay guards,
  and strict assignment IDs constrain runtime submissions.
- The verifier has read-only repository access and cannot push or settle.

## Host hardening

Enable TLS, secure cookies, HSTS, restricted CORS/CSRF origins, least-privilege
service users, encrypted secret storage, PostgreSQL network isolation, log
redaction/rotation, and outbound allow-lists where practical. Keep agent
workspaces on disposable storage outside identity and secret directories.

The bundled scripts and defaults are development/testnet oriented. A successful
test suite does not replace a production threat model, dependency review,
contract audit, secret rotation plan, or incident response procedure.
