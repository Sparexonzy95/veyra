# Changelog

## v0.4.0

- Enforced client/agent/verifier separation per job.
- Added fixed claim-to-submission deadlines and abandoned-claim refunds.
- Changed verifier grace to start at submission time.
- Made agent/verifier revocation effective immediately.
- Domain-bound verification report commitments.
- Awarded Karma once per unique client address.
- Added abandoned-job metrics.
- Added cross-function reentrancy protection.
- Hardened Arc deployment against wrong token and same agent/verifier wallet.
- Expanded suite from 37 to 45 passing adversarial tests.

## v0.3.0

- Initial self-contained Arc USDC escrow.
