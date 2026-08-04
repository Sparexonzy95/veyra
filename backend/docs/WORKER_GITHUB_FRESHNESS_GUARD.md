# Veyra Worker GitHub Freshness Guard

This phase adds a read-only task freshness gate before a funded Arc job may stay
in the worker claim queue.

## Guard order

1. Verify the worker and Arc job are still eligible.
2. Verify Arc and Django commitments still match.
3. Select the lowest open Arc job ID as the canonical job when multiple funded
   jobs target the same GitHub repository issue.
4. Read the committed GitHub issue.
5. Reject missing, closed, or pull-request targets.
6. Inspect all recent pull requests from the connected worker account.
7. Block when the worker already has an open or merged pull request for the issue.
8. Inspect the worker fork and block when a Veyra issue branch already exists.
9. Queue only when all checks pass.

## Queue states

- `QUEUED`: Arc and GitHub checks passed.
- `DEFERRED`: a temporary Arc/GitHub read failed or worker capacity is full.
- `STALE`: the issue or onchain job is no longer open.
- `BLOCKED`: an existing worker PR/branch or fork collision prevents safe work.
- `DUPLICATE`: another funded OPEN Arc job already targets the same repo/issue.
- `INELIGIBLE`: a permanent policy, skill, commitment, invitation, or budget gate failed.

## Safety properties

The freshness guard is read-only. It does not claim a job, submit a Circle
transaction, move USDC, clone a repository, create a branch, push code, or open
a pull request.

The GitHub token is read only from the runtime environment and is never included
in queue snapshots, logs, command output, Django records, or OpenCode input.

The future claim service must call the same `evaluate_job()` guard again inside
the claim lock immediately before submitting the Circle transaction. Discovery
results are advisory snapshots and must never be treated as permanent approval.

## Commands

```powershell
python manage.py check_worker_job_freshness --job-id 3
python manage.py discover_worker_jobs
python manage.py show_worker_job_queue
```
