from __future__ import annotations

from workers.models import WorkerAgent, WorkerJobAssignment


ACTIVE_ASSIGNMENT_STATUSES = {
    WorkerJobAssignment.Status.RESERVED,
    WorkerJobAssignment.Status.CLAIMING,
    WorkerJobAssignment.Status.CLAIMED,
    WorkerJobAssignment.Status.LEASED,
    WorkerJobAssignment.Status.EXECUTING,
    WorkerJobAssignment.Status.RESULT_RECEIVED,
    WorkerJobAssignment.Status.SUBMITTING,
    WorkerJobAssignment.Status.SUBMITTED,
    WorkerJobAssignment.Status.VERIFYING,
    WorkerJobAssignment.Status.SETTLING,
}


def active_assignment_count(
    worker: WorkerAgent,
    *,
    exclude_queue_item_id=None,
) -> int:
    """Return authoritative worker capacity usage.

    Queue rows are discovery projections and can outlive a released or failed
    assignment. Only an active assignment may consume execution capacity.
    """

    values = WorkerJobAssignment.objects.filter(
        worker=worker,
        status__in=ACTIVE_ASSIGNMENT_STATUSES,
    )
    if exclude_queue_item_id:
        values = values.exclude(queue_item_id=exclude_queue_item_id)
    return values.count()
