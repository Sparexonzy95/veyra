import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from jobs.models import VeyraJob
from workers.models import (
    HostedAgentConnection,
    WorkerJobAssignment,
    WorkerQualificationRun,
)

job = VeyraJob.objects.get(onchain_job_id=6)
assignment = WorkerJobAssignment.objects.select_related(
    "worker",
    "queue_item",
).get(job=job)

print("=== JOB #6 ASSIGNMENT ===")
print("ASSIGNMENT ID:", assignment.id)
print("ASSIGNMENT STATUS:", assignment.status)
print("ASSIGNED WORKER ID:", assignment.worker_id)
print("ASSIGNED WORKER NAME:", assignment.worker.name)
print("ASSIGNED WORKER ROLE:", assignment.worker.agent_role)
print("LEASE ID:", assignment.execution_lease_id)
print("RUNTIME LAST SEEN:", assignment.runtime_last_seen_at)

print()
print("=== HOSTED RUNTIME CONNECTIONS ===")

connections = (
    HostedAgentConnection.objects
    .select_related("worker")
    .order_by("-last_seen_at", "-created_at")
)

if not connections.exists():
    print("NO HOSTED RUNTIME CONNECTIONS FOUND")

for connection in connections:
    print("---")
    print("CONNECTION ID:", connection.id)
    print("WORKER ID:", connection.worker_id)
    print("WORKER NAME:", connection.worker.name)
    print("WORKER ROLE:", connection.worker.agent_role)
    print("CONNECTION STATUS:", connection.status)
    print("PROVIDER READY:", connection.provider_ready)
    print("PROVIDER:", connection.provider)
    print("MODEL:", connection.model_name)
    print("LAST SEEN:", connection.last_seen_at)
    print(
        "MATCHES JOB #6 WORKER:",
        connection.worker_id == assignment.worker_id,
    )

print()
print("=== QUALIFICATION RUNS ===")

runs = WorkerQualificationRun.objects.filter(
    worker=assignment.worker
).order_by("-created_at")[:5]

if not runs:
    print("NO QUALIFICATION RUNS FOUND")

for run in runs:
    print("---")
    print("RUN ID:", run.id)
    print("STATUS:", run.status)
    print("ATTEMPT:", run.attempt_number)
    print("LEASE EXPIRES:", run.lease_expires_at)
    print("FAILURE:", run.failure_message)
