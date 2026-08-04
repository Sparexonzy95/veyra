# Veyra Worker Activation — Phase 2 Step 2

This step runs the first controlled coding assignment for the Veyra Code Agent.

## Fixed test target

- Repository: `https://github.com/sparexonzy95/veyra-agent-test-api`
- Issue: `https://github.com/sparexonzy95/veyra-agent-test-api/issues/1`
- Repository type: public
- Worker account: `logicbloomlab`
- Engine: OpenCode using `zai-org/glm-5.2`

The command refuses a private, archived, disabled, closed, or mismatched repository/issue.

## Execution stages

1. Verify Git, OpenCode non-interactive run mode, GitHub identity, token scope, and workspace access.
2. Read the public repository and open issue from GitHub.
3. Create a database record for the controlled test.
4. Clone the source repository into `~/Veyra-Worker-Workspaces`.
5. Create an isolated Python virtual environment.
6. Validate `requirements.txt` and install wheel-only dependencies.
7. Run baseline Pytest checks.
8. Run OpenCode inside the cloned repository.
9. Inspect changed paths, reject protected/secret-like files, reject binaries, renames, workflow edits, oversized changes, and path traversal.
10. Run Pytest after the change.
11. Commit only after validation passes.
12. Create or reuse the `logicbloomlab` fork.
13. Push the controlled branch without placing the GitHub token in the remote URL.
14. Open a pull request to the original repository.
15. Mark the assignment passed and move the worker to `ACTIVE`.

General job discovery remains disabled. A later phase will implement the job-discovery queue and explicitly enable discovery.

## Secret handling

The GitHub token remains in the backend environment and a short-lived Git askpass helper. It is not stored in Django, the Git remote URL, commit metadata, or command output.

Before starting OpenCode, Veyra removes the Circle API key, Circle entity secret, GitHub tokens, Django secret key, and database URL from the child process environment.

This is process-environment isolation, not a complete operating-system sandbox. The OpenCode prompt forbids access outside the workspace, but production should run workers in a dedicated container or restricted operating-system account.

## Commands

```powershell
python manage.py migrate
python manage.py preflight_worker_test_runtime
python manage.py prepare_worker_test_assignment
python manage.py run_worker_test_assignment
python manage.py show_worker_test_assignment
```

## Passing result

```text
Assignment status: PASSED
Post-change tests passed: True
Pull request: https://github.com/sparexonzy95/veyra-agent-test-api/pull/...
Worker status: ACTIVE
Test assignment passed: True
Discovery enabled: False
```

## Failure behavior

A failed stage records a sanitized failure stage/message, leaves the workspace for inspection, does not push unvalidated code, does not open a pull request, and does not activate the worker.

To retry, inspect the failed assignment with `show_worker_test_assignment`, remove only that failed workspace after checking it, then prepare a new assignment.
