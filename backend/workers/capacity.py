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
}


def active_assignment_count(
    worker: WorkerAgent,
    *,
    exclude_queue_item_id=None,
) -> int:
    """Return authoritative worker capacity usage.

    Queue rows are discovery projections and can outlive a released or failed
    assignment. Capacity represents coding-runtime responsibility only. The
    coding slot stays occupied through PR/on-chain submission and is released
    once the assignment reaches SUBMITTED. Independent verification and Arc
    settlement do not keep the coding agent artificially busy.
    """

    values = WorkerJobAssignment.objects.filter(
        worker=worker,
        status__in=ACTIVE_ASSIGNMENT_STATUSES,
    )
    if exclude_queue_item_id:
        values = values.exclude(queue_item_id=exclude_queue_item_id)
    return values.count()
