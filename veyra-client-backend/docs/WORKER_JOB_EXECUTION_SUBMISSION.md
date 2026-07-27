# Worker Job Execution and Arc Submission

Phase 3 Step 4 completes a claimed software job without exposing runtime secrets.

## Execution lifecycle

1. Read-only preflight confirms Arc still records the worker as provider.
2. GitHub freshness is checked again.
3. The public repository is cloned into a contained workspace.
4. Dependencies are installed in an isolated virtual environment.
5. Only allowlisted committed Pytest commands are executed.
6. OpenCode receives the immutable committed task package, not secrets.
7. Changed files are inspected against protected and committed path rules.
8. Validation commands are run again.
9. Veyra commits, pushes with temporary non-interactive Git credentials, and opens a pull request.
10. Queue status becomes `SUBMISSION_PENDING`.

## Arc submission lifecycle

1. Read-only preflight verifies the PR head SHA, branch, base branch, Arc provider, and deadline.
2. The 40-character Git SHA is committed as `keccak256(lowercase_git_sha)`.
3. The contract computes the deterministic deliverable hash.
4. The Circle developer-controlled SCA submits `submitWork(uint256,bytes32,uint64)`.
5. Circle and Arc are reconciled without blind retries.
6. The `WorkSubmitted` event and final Arc job state are verified.
7. Queue status becomes `SUBMITTED`; the client projection becomes `UNDER_REVIEW`.

## Safety rules

- GitHub, Circle, OpenCode, wallet, and recovery secrets are never stored in Django.
- User-provided shell commands are never executed directly.
- Phase 3 currently accepts only committed Pytest validation commands.
- Browser prompts are disabled for Git pushes.
- Uncertain Circle outcomes require reconciliation, not a second transaction.
- Pull-request publication and Arc submission are separate confirmation-gated operations.
