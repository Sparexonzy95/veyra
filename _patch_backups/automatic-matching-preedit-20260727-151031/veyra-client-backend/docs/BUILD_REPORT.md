# Veyra Django Client Backend Build Report

Version: 0.1.0

## Architecture correction

- Backend: Django + Django REST Framework
- Database: PostgreSQL-first, SQLite fallback for local tests
- Frontend reference: GrantFox design only
- Removed from backend architecture: Next.js API routes, Prisma, Supabase authority

## Included

- Circle social device-token endpoint
- Circle email OTP bootstrap endpoint
- provisional Circle session exchange
- wallet-bound Veyra identity
- HTTP-only Veyra sessions
- additive CLIENT capability
- Arc Testnet user-controlled SCA provisioning
- wallet sync and USDC balance
- simple client dashboard API
- public GitHub issue import
- job drafts, review, and editable pre-funding state
- immutable funding snapshot created only when funding starts
- canonical commitment hashes
- exact USDC approval challenge
- deployed Veyra `createJob` challenge
- Circle transaction callback verification
- Arc event indexer
- contextual cancel/refund endpoint
- notifications and audit records
- OpenAPI schema
- Docker/PostgreSQL local setup

## Validated locally

- Django system check
- migrations generated and applied
- 11 automated tests
- deployed function selectors
- simple job-draft API
- provisional and returning-user auth paths
- wallet sync and CLIENT capability
- review → approval challenge → funding challenge
- clean OpenAPI generation
- Python bytecode compilation

## Not executed locally

Real Circle, PostgreSQL network, GitHub network, and Arc Testnet transactions require the developer's credentials and connected environment. The source contains no real API key, entity secret, user token, encryption key, or private key.
