"""Read side of the member portal: what a signed-in member sees about themselves (in memory only)."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess.models import Club, Fee, Member, Membership, MembershipStatus
from ess.services import ecp_content, members
from ess.services.members import MemberData


@dataclass
class Home:
    member: Member
    data: MemberData
    clubs: list[tuple[str, MembershipStatus, bool]] = field(default_factory=list)  # (club, status, primary)
    paid_years: list[int] = field(default_factory=list)
    payment: tuple[str, str] | None = None  # (PAYMe URL, label) while the fee is due
    valid_until: date | None = None


def home(session: Session, member: Member) -> Home:
    rows = session.execute(select(Club.name, Membership.status, Membership.is_primary)
                           .join(Club, Club.id == Membership.club_id)
                           .where(Membership.member_id == member.id, Membership.valid_to.is_(None))).all()
    paid = sorted(session.scalars(select(Fee.year).where(Fee.member_id == member.id, Fee.paid_at.is_not(None))),
                  reverse=True)
    return Home(member=member, data=members.read_member(member),
                clubs=[(name, status, primary) for name, status, primary in
                       sorted(rows, key=lambda r: (not r[2], r[0]))],
                paid_years=paid, payment=ecp_content.payment_link(session, member.id),
                valid_until=date(paid[0], 12, 31) if paid else None)
