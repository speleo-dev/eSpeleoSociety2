"""Requests waiting for an administrator ("Požiadavky").

Other services open and close tasks in the same transaction as the change they belong to. Actions an
administrator starts from the task list (activate, reject, decide) are implemented here and delegate
to the membership and member services, which close the task.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Club, Member, Membership, MembershipStatus, Task, TaskStatus, TaskType
from ess.services.access import Actor, DomainError, require_admin


def open_task(
    session: Session,
    actor: Actor,
    task_type: TaskType,
    member_id: uuid.UUID,
    membership_id: uuid.UUID | None = None,
    club_id: uuid.UUID | None = None,
    context: dict | None = None,
) -> Task:
    """Open a task unless the same one is already open (idempotent)."""
    query = select(Task).where(
        Task.status == TaskStatus.OPEN.value, Task.task_type == task_type.value, Task.member_id == member_id
    )
    if membership_id:
        query = query.where(Task.membership_id == membership_id)
    existing = session.scalar(query)
    if existing:
        return existing
    task = Task(
        id=uuid.uuid4(),
        task_type=task_type.value,
        status=TaskStatus.OPEN.value,
        member_id=member_id,
        membership_id=membership_id,
        club_id=club_id,
        context=context,
        requested_by=actor.id,
    )
    session.add(task)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="task.open",
                 entity_type="task", entity_id=str(task.id), details={"type": task_type.value})
    return task


def close_tasks(
    session: Session,
    actor: Actor,
    task_type: TaskType,
    status: TaskStatus,
    resolution: str,
    *,
    member_id: uuid.UUID | None = None,
    membership_id: uuid.UUID | None = None,
    note: str | None = None,
) -> int:
    """Close open tasks of a type for a member or membership. Returns the number closed."""
    query = select(Task).where(Task.status == TaskStatus.OPEN.value, Task.task_type == task_type.value)
    if member_id:
        query = query.where(Task.member_id == member_id)
    if membership_id:
        query = query.where(Task.membership_id == membership_id)
    count = 0
    for task in session.scalars(query):
        task.status = status.value
        task.resolution = resolution
        task.resolution_note = (note or "").strip() or None
        task.resolved_by = actor.id
        task.resolved_at = datetime.now(timezone.utc)
        audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="task.close",
                     entity_type="task", entity_id=str(task.id),
                     details={"type": task.task_type, "status": status.value, "resolution": resolution})
        count += 1
    session.flush()
    return count


def cancel_all_for_member(session: Session, actor: Actor, member_id: uuid.UUID, resolution: str) -> None:
    for task_type in TaskType:
        close_tasks(session, actor, task_type, TaskStatus.CANCELLED, resolution, member_id=member_id)


def _get_open(session: Session, task_id: uuid.UUID, task_type: TaskType) -> Task:
    task = session.get(Task, task_id)
    if task is None or task.status != TaskStatus.OPEN.value or task.task_type != task_type.value:
        raise DomainError("task_not_open")
    return task


# --- actions started from the task list -----------------------------------------------------------

def activate(session: Session, actor: Actor, task_id: uuid.UUID) -> None:
    from ess.services import memberships

    require_admin(actor)
    task = _get_open(session, task_id, TaskType.MEMBER_ACTIVATION)
    memberships.activate(session, actor, task.membership_id)


def reject_activation(session: Session, actor: Actor, task_id: uuid.UUID, reason: str, on: date | None = None) -> None:
    """Reject a proposed member. A promoted candidate goes back to candidate; a new member's proposal ends."""
    from ess.services import memberships

    require_admin(actor)
    if not reason.strip():
        raise DomainError("reason_required")
    task = _get_open(session, task_id, TaskType.MEMBER_ACTIVATION)
    was_candidate = (task.context or {}).get("from_status") == MembershipStatus.CANDIDATE.value
    if was_candidate:
        memberships.change_status(session, actor, task.membership_id, MembershipStatus.CANDIDATE, on,
                                  _task_resolution=("rejected", reason))
    else:
        memberships.terminate(session, actor, task.membership_id, on, _task_resolution=("rejected", reason))


def keep_as_unaffiliated(session: Session, actor: Actor, task_id: uuid.UUID) -> None:
    from ess.services import members

    task = _get_open(session, task_id, TaskType.SSS_DECISION)
    members.restore_to_unaffiliated(session, actor, task.member_id)


def end_sss(session: Session, actor: Actor, task_id: uuid.UUID, note: str) -> None:
    from ess.services import members

    task = _get_open(session, task_id, TaskType.SSS_DECISION)
    members.end_sss_membership(session, actor, task.member_id, note)


# --- reading --------------------------------------------------------------------------------------

@dataclass
class TaskRow:
    task: Task
    full_name: str
    club_name: str | None


def count_open(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Task).where(Task.status == TaskStatus.OPEN.value)) or 0


def list_tasks(session: Session, open_only: bool = True, task_type: str | None = None, limit: int = 200) -> list[TaskRow]:
    from ess.services.members import read_member

    query = select(Task, Member, Club).join(Member, Member.id == Task.member_id).outerjoin(Club, Club.id == Task.club_id)
    if open_only:
        query = query.where(Task.status == TaskStatus.OPEN.value).order_by(Task.created_at)
    else:
        query = query.where(Task.status != TaskStatus.OPEN.value).order_by(Task.resolved_at.desc()).limit(limit)
    if task_type:
        query = query.where(Task.task_type == task_type)
    return [TaskRow(task, read_member(member).full_name(), club.name if club else None)
            for task, member, club in session.execute(query)]


def membership_of(session: Session, task: Task) -> Membership | None:
    return session.get(Membership, task.membership_id) if task.membership_id else None
