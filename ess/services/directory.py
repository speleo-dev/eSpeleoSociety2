"""Read-side queries for the administration (lists and details with decrypted names).

Personal data is decrypted in memory only. Queries are kept to a handful per page because the
database is reached over the internet.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ess.models import Club, Member, Membership, MembershipStatus, OrgPosition, PositionHolder
from ess.security.crypto import normalize_for_index
from ess.services.members import MemberData, SssStatus, read_member


@dataclass
class MemberRow:
    id: uuid.UUID
    data: MemberData
    clubs: list[tuple[str, MembershipStatus, bool]] = field(default_factory=list)  # (club, status, primary)
    sss_status: SssStatus = SssStatus.NEVER

    @property
    def sort_key(self) -> tuple[str, str]:
        return normalize_for_index(self.data.last_name), normalize_for_index(self.data.first_name)


def _sss_status(member: Member, has_open: bool, had_any: bool) -> SssStatus:
    if member.expelled_at:
        return SssStatus.EXPELLED
    if has_open:
        return SssStatus.MEMBER
    if member.sss_ended_at:
        return SssStatus.ENDED
    return SssStatus.AWAITING_DECISION if had_any else SssStatus.NEVER


def list_members(
    session: Session,
    query: str | None = None,
    club_id: uuid.UUID | None = None,
    status: MembershipStatus | None = None,
) -> list[MemberRow]:
    clubs = {c.id: c.name for c in session.scalars(select(Club))}
    open_by_member: dict[uuid.UUID, list[Membership]] = defaultdict(list)
    for m in session.scalars(select(Membership).where(Membership.valid_to.is_(None))):
        open_by_member[m.member_id].append(m)
    had_any = set(session.scalars(select(Membership.member_id).distinct()))

    needle = normalize_for_index(query) if query else None
    rows = []
    for member in session.scalars(select(Member)):
        open_ms = open_by_member.get(member.id, [])
        if club_id and not any(m.club_id == club_id for m in open_ms):
            continue
        if status and not any(m.status == status and (not club_id or m.club_id == club_id) for m in open_ms):
            continue
        data = read_member(member)
        if needle:
            haystack = normalize_for_index(f"{data.first_name} {data.last_name} {data.email or ''} {data.card_number or ''}")
            if needle not in haystack:
                continue
        rows.append(
            MemberRow(
                id=member.id,
                data=data,
                clubs=[(clubs[m.club_id], m.status, m.is_primary) for m in sorted(open_ms, key=lambda m: not m.is_primary)],
                sss_status=_sss_status(member, bool(open_ms), member.id in had_any),
            )
        )
    rows.sort(key=lambda r: r.sort_key)
    return rows


@dataclass
class MembershipView:
    membership: Membership
    club_name: str
    can_chair_manage: bool


@dataclass
class PositionView:
    name: str
    club_name: str | None
    valid_from: date
    valid_to: date | None


@dataclass
class MemberDetail:
    member: Member
    data: MemberData
    sss_status: SssStatus
    open_memberships: list[MembershipView]
    history: list[MembershipView]
    positions: list[PositionView]


def member_detail(session: Session, member_id: uuid.UUID) -> MemberDetail | None:
    member = session.get(Member, member_id)
    if member is None:
        return None
    clubs = {c.id: c for c in session.scalars(select(Club))}
    all_ms = list(
        session.scalars(
            select(Membership).where(Membership.member_id == member_id).order_by(Membership.valid_from.desc(), Membership.created_at.desc())
        )
    )
    views = [MembershipView(m, clubs[m.club_id].name, not clubs[m.club_id].is_unaffiliated) for m in all_ms]
    position_names = {p.code: p.name for p in session.scalars(select(OrgPosition))}
    holders = session.scalars(
        select(PositionHolder).where(PositionHolder.member_id == member_id).order_by(PositionHolder.valid_from.desc())
    )
    return MemberDetail(
        member=member,
        data=read_member(member),
        sss_status=_sss_status(member, any(v.membership.valid_to is None for v in views), bool(views)),
        open_memberships=[v for v in views if v.membership.valid_to is None],
        history=views,
        positions=[
            PositionView(position_names[h.position_code], clubs[h.club_id].name if h.club_id else None, h.valid_from, h.valid_to)
            for h in holders
        ],
    )


@dataclass
class PendingActivation:
    membership_id: uuid.UUID
    member_id: uuid.UUID
    full_name: str
    club_name: str
    since: date


def pending_activations(session: Session) -> list[PendingActivation]:
    rows = session.execute(
        select(Membership, Member, Club)
        .join(Member, Member.id == Membership.member_id)
        .join(Club, Club.id == Membership.club_id)
        .where(Membership.valid_to.is_(None), Membership.status == MembershipStatus.PENDING_ACTIVATION)
    ).all()
    result = [
        PendingActivation(ms.id, member.id, read_member(member).full_name(), club.name, ms.valid_from)
        for ms, member, club in rows
    ]
    return sorted(result, key=lambda p: (p.since, normalize_for_index(p.full_name)))


@dataclass
class ClubRow:
    club: Club
    chair_name: str | None
    counts: dict[MembershipStatus, int]


def clubs_overview(session: Session) -> list[ClubRow]:
    counts: dict[uuid.UUID, dict[MembershipStatus, int]] = defaultdict(dict)
    for club_id, status, n in session.execute(
        select(Membership.club_id, Membership.status, func.count())
        .where(Membership.valid_to.is_(None))
        .group_by(Membership.club_id, Membership.status)
    ):
        counts[club_id][status] = n
    chairs = {
        club_id: member
        for club_id, member in session.execute(
            select(PositionHolder.club_id, Member)
            .join(Member, Member.id == PositionHolder.member_id)
            .where(PositionHolder.position_code == "club_chair", PositionHolder.valid_to.is_(None))
        )
    }
    rows = [
        ClubRow(club, read_member(chairs[club.id]).full_name() if club.id in chairs else None, counts.get(club.id, {}))
        for club in session.scalars(select(Club).order_by(Club.is_unaffiliated.desc(), Club.name))
    ]
    return rows


def dashboard_counts(session: Session) -> dict[str, int]:
    from ess.services.members import awaiting_decision

    return {
        "pending_activations": session.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.valid_to.is_(None), Membership.status == MembershipStatus.PENDING_ACTIVATION
            )
        ),
        "awaiting_decision": len(awaiting_decision(session)),
        "sss_members": session.scalar(
            select(func.count(func.distinct(Membership.member_id))).where(Membership.valid_to.is_(None))
        ),
        "clubs": session.scalar(select(func.count()).select_from(Club).where(Club.active, ~Club.is_unaffiliated)),
    }
