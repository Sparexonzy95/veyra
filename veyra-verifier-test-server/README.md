# Veyra independent verifier runtime

This is a second isolated runtime identity. It must not reuse LogicBloom's
`.veyra-runtime` directory or Ed25519 key.

Local demo:

- LogicBloom worker runtime: port 9100
- CodeSentinel verifier runtime: port 9200

Production:

Run this verifier process on a separate VM/container, preferably under a
different operator and AI-provider account. It receives repository-scoped
read-only GitHub App credentials and cannot push, commit, open PRs, or sign Arc
settlement transactions.
