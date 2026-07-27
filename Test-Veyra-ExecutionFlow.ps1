param(
    [int]$OnchainJobId = 6,
    [string]$ProjectRoot = "C:\Users\cashkink\Downloads\Veyra-backend"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$backend = Join-Path $ProjectRoot "veyra-client-backend"
$diagnostic = Join-Path $backend "_diagnose_execution_flow_tmp.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Veyra Python was not found: $python"
}
if (-not (Test-Path -LiteralPath $backend)) {
    throw "Veyra backend was not found: $backend"
}

Write-Host "=== LOGICBLOOM RUNTIME ===" -ForegroundColor Cyan
try {
    $workerHealth = Invoke-RestMethod "http://127.0.0.1:9100/veyra/health" -TimeoutSec 10
    $workerHealth | Select-Object runtime_role, provider_ready, paired, connected, healthy, last_heartbeat_at, last_heartbeat_error | Format-List
}
catch {
    Write-Host "LogicBloom health endpoint is unavailable: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "=== CODESENTINEL RUNTIME ===" -ForegroundColor Cyan
try {
    $verifierHealth = Invoke-RestMethod "http://127.0.0.1:9200/veyra/health" -TimeoutSec 10
    $verifierHealth | Select-Object runtime_role, provider_ready, paired, connected, healthy, last_heartbeat_at, last_heartbeat_error | Format-List
}
catch {
    Write-Host "CodeSentinel health endpoint is unavailable: $($_.Exception.Message)" -ForegroundColor Red
}

$pythonSource = @'
import json
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from jobs.models import VeyraJob
from workers.models import WorkerJobAssignment, WorkerJobQueueItem
from workers.runtime_status import runtime_snapshot

job_id = int(sys.argv[1])
job = VeyraJob.objects.filter(onchain_job_id=job_id).first()
if job is None:
    print(json.dumps({"job_found": False, "onchain_job_id": job_id}, indent=2))
    raise SystemExit(2)

assignment = (
    WorkerJobAssignment.objects
    .select_related("worker", "queue_item")
    .filter(job=job)
    .first()
)

payload = {
    "job_found": True,
    "database_job_id": str(job.id),
    "onchain_job_id": int(job.onchain_job_id),
    "job_status": job.status,
    "client_status": job.client_status,
    "assignment": None,
}

if assignment is not None:
    item = assignment.queue_item
    runtime = runtime_snapshot(assignment.worker)
    payload["assignment"] = {
        "id": str(assignment.id),
        "status": assignment.status,
        "attempt": int(assignment.assignment_attempt),
        "worker_id": str(assignment.worker_id),
        "worker_name": assignment.worker.name,
        "lease_id": str(assignment.execution_lease_id or ""),
        "lease_expires_at": assignment.lease_expires_at.isoformat() if assignment.lease_expires_at else None,
        "runtime_last_seen_at": assignment.runtime_last_seen_at.isoformat() if assignment.runtime_last_seen_at else None,
        "failure_stage": assignment.failure_stage,
        "failure_message": assignment.failure_message,
        "queue_status": item.status,
        "execution_attempts": int(item.execution_attempt_count),
        "execution_failure_stage": item.execution_failure_stage,
        "execution_failure_message": item.execution_failure_message,
        "commit_sha": item.execution_commit_sha,
        "pull_request_url": item.execution_pull_request_url,
        "claim_confirmed_at": item.claim_confirmed_at.isoformat() if item.claim_confirmed_at else None,
        "runtime": {
            "status": runtime.get("status"),
            "connected": bool(runtime.get("connected")),
            "provider_ready": bool(runtime.get("provider_ready")),
            "last_seen_at": runtime.get("last_seen_at").isoformat() if runtime.get("last_seen_at") else None,
            "health_message": runtime.get("health_message"),
        },
    }

print(json.dumps(payload, indent=2))
'@

try {
    $pythonSource | Set-Content -LiteralPath $diagnostic -Encoding UTF8
    Push-Location $backend
    try {
        & $python $diagnostic $OnchainJobId
        if ($LASTEXITCODE -ne 0) {
            throw "Database execution-flow diagnostic failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if (Test-Path -LiteralPath $diagnostic) {
        Remove-Item -LiteralPath $diagnostic -Force
    }
}
