# Veyra verifier

The verifier runs the Agent Starter engine in the separate `VERIFIER` role. It
uses its own runtime identity and model provider account, receives
repository-scoped read-only GitHub credentials, and returns signed verification
evidence. It cannot push commits, open pull requests, or sign Arc settlement
transactions.

For the local demo, the worker listens on port `9100` and the verifier on
`9200`. Copy `.env.example` to `.env`, add a distinct verifier provider key, and
run `start-verifier.ps1`. Production should isolate the verifier process from
the demo agent, ideally under a different operator or host.
