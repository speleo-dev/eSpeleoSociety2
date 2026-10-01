"""Read side of the member portal: what a signed-in member sees about themselves (in memory only)."""

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess.models import Club, Fee, Member, Membership, MembershipStatus
from ess.security.crypto import normalize_for_index
from ess.services import delegations, documents, ecp_content, members
from ess.services.access import DomainError, managed_club_ids
from ess.services.members import MemberData


@dataclass
class Home:
    member: Member
    data: MemberData
    clubs: list[tuple[Club, MembershipStatus, bool]] = field(default_factory=list)  # (club, status, primary)
    paid_years: list[int] = field(default_factory=list)
    payment: tuple[str, str] | None = None  # (PAYMe URL, label) while the fee is due
    valid_until: date | None = None
    documents: list = field(default_factory=list)


def home(session: Session, member: Member) -> Home:
    rows = session.execute(select(Club, Membership.status, Membership.is_primary)
                           .join(Club, Club.id == Membership.club_id)
                           .where(Membership.member_id == member.id, Membership.valid_to.is_(None))).all()
    paid = sorted(session.scalars(select(Fee.year).where(Fee.member_id == member.id, Fee.paid_at.is_not(None))),
                  reverse=True)
    return Home(member=member, data=members.read_member(member),
                clubs=[(club, status, primary) for club, status, primary in
                       sorted(rows, key=lambda r: (not r[2], r[0].name))],
                paid_years=paid, payment=ecp_content.payment_link(session, member.id),
                valid_until=date(paid[0], 12, 31) if paid else None,
                documents=documents.valid_documents(session))


# --- club page (R37) ---------------------------------------------------------------------------------


@dataclass
class ClubMemberRow:
    member_id: uuid.UUID
    data: MemberData
    status: MembershipStatus
    is_chair: bool = False
    has_ecp: bool = False


@dataclass
class ClubView:
    club: Club
    full: bool  # the chair (also while represented) and the delegate see all data; others name, status, contacts
    can_manage: bool  # manages the club now (chair without a delegate, or the delegate)
    is_chair: bool
    is_delegate: bool
    delegate_name: str | None
    chair_name: str | None
    rows: list[ClubMemberRow]
    delegate_options: list[ClubMemberRow] = field(default_factory=list)  # for the chair to choose from


def club_view(session: Session, member: Member, club_id: uuid.UUID) -> ClubView:
    """A club of the signed-in member. Every member of the club may read it (R37)."""
    club = session.get(Club, club_id)
    own = session.scalar(select(Membership.id).where(Membership.member_id == member.id, Membership.club_id == club_id,
                                                     Membership.valid_to.is_(None)))
    if club is None or own is None or club.is_unaffiliated:
        raise DomainError("club_not_found")
    chair_id = delegations.current_chair_id(session, club_id)
    delegation = delegations.current(session, club_id)
    is_chair = chair_id == member.id
    is_delegate = delegation is not None and delegation.delegate_member_id == member.id
    can_manage = club_id in managed_club_ids(session, member.id)
    full = is_chair or is_delegate or can_manage
    # Every member of the club sees everybody in it, candidates too (contacts for club events, R42).
    query = (select(Member, Membership.status).join(Membership, Membership.member_id == Member.id)
             .where(Membership.club_id == club_id, Membership.valid_to.is_(None)))
    from ess.services.directory import ecp_holders

    with_ecp = ecp_holders(session) if full else set()
    rows = [ClubMemberRow(m.id, members.read_member(m), status, m.id == chair_id, m.id in with_ecp)
            for m, status in session.execute(query)]
    rows.sort(key=lambda r: (normalize_for_index(r.data.last_name), normalize_for_index(r.data.first_name)))
    names = {r.member_id: r.data.full_name() for r in rows}
    eligible = set(delegations.eligible_ids(session, club_id)) if is_chair and delegation is None else set()
    return ClubView(club=club, full=full, can_manage=can_manage, is_chair=is_chair, is_delegate=is_delegate,
                    delegate_name=names.get(delegation.delegate_member_id) if delegation else None,
                    chair_name=names.get(chair_id) if chair_id else None, rows=rows,
                    delegate_options=[r for r in rows if r.member_id in eligible])


# --- menu for members and chairs (R52) -----------------------------------------------------------------


def own_club_ids(session: Session, member: Member) -> list[uuid.UUID]:
    """Clubs the member belongs to now (not "SSS – nezaradení"), primary first."""
    rows = session.execute(select(Club.id, Club.name, Membership.is_primary).join(Membership, Membership.club_id == Club.id)
                           .where(Membership.member_id == member.id, Membership.valid_to.is_(None),
                                  Club.is_unaffiliated.is_(False))).all()
    return [r[0] for r in sorted(rows, key=lambda r: (not r[2], r[1]))]


@dataclass
class ClubInfo:
    club: Club
    chair_name: str | None
    own: bool  # the member belongs to it
    manages: bool  # the member manages it (chair without a delegate, or the delegate)


def clubs_info(session: Session, member: Member) -> list[ClubInfo]:
    """All active clubs with public contacts and the chair's name (R52)."""
    from ess.models import PositionHolder

    own = set(own_club_ids(session, member))
    managed = managed_club_ids(session, member.id)
    chairs = dict(session.execute(select(PositionHolder.club_id, Member).join(Member, Member.id == PositionHolder.member_id)
                                  .where(PositionHolder.position_code == "club_chair",
                                         PositionHolder.valid_to.is_(None))).all())
    clubs = session.scalars(select(Club).where(Club.active, Club.is_unaffiliated.is_(False))).all()
    rows = [ClubInfo(c, members.read_member(chairs[c.id]).full_name() if c.id in chairs else None, c.id in own,
                     c.id in managed) for c in clubs]
    return sorted(rows, key=lambda r: normalize_for_index(r.club.name))


def club_info(session: Session, member: Member, club_id: uuid.UUID) -> ClubInfo:
    for row in clubs_info(session, member):
        if row.club.id == club_id:
            return row
    raise DomainError("club_not_found")
