"""Kartička SSS: issued by an administrator for one calendar year, with its own random code.

Until payments exist (phase 3) the administrator issues the card after checking that the SSS fee for the
year is paid. Only the SHA-256 hash of the code is stored; issuing again for the same year replaces the
previous card (its code stops working).
"""

import enum
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.cards import CardContent
from ess.models import Club, Member, Membership, SssCard
from ess.services import members
from ess.services.access import PUBLIC, Actor, DomainError, require_admin


def hash_code(code: str) -> bytes:
    return hashlib.sha256(code.encode("ascii", errors="ignore")).digest()


@dataclass
class IssuedCard:
    card: SssCard
    code: str
    content: CardContent
    email: str | None
    first_name: str


def issue(session: Session, actor: Actor, member_id: uuid.UUID, year: int, base_url: str) -> IssuedCard:
    require_admin(actor)
    this_year = date.today().year
    if not (this_year - 1 <= year <= this_year + 1):
        raise DomainError("invalid_card_year")
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if member.expelled_at or member.sss_ended_at:
        raise DomainError("member_not_in_sss")
    now = datetime.now(UTC)
    for old in session.scalars(select(SssCard).where(SssCard.member_id == member_id, SssCard.year == year,
                                                     SssCard.revoked_at.is_(None))):
        old.revoked_at = now
    session.flush()
    code = secrets.token_urlsafe(18)
    card = SssCard(id=uuid.uuid4(), member_id=member_id, year=year, code_hash=hash_code(code), issued_by=actor.id)
    session.add(card)
    session.flush()
    data = members.read_member(member)
    club = session.scalar(select(Club).join(Membership, Membership.club_id == Club.id).where(
        Membership.member_id == member_id, Membership.valid_to.is_(None), Membership.is_primary))
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="sss_card.issue",
                 entity_type="sss_card", entity_id=str(card.id), details={"year": year})
    content = CardContent(full_name=data.full_name(), club_name=club.name if club else "",
                          card_number=data.card_number, year=year, verify_url=f"{base_url.rstrip('/')}/k/{code}")
    return IssuedCard(card, code, content, data.email, data.first_name)


class CardOutcome(str, enum.Enum):
    VALID = "valid"
    OTHER_YEAR = "other_year"  # a card for a past (or future) year
    INVALID = "invalid"  # unknown, replaced, or the holder is no longer a member of SSS


@dataclass
class CardCheck:
    outcome: CardOutcome
    year: int | None = None


def verify(session: Session, code: str) -> CardCheck:
    card = session.scalar(select(SssCard).where(SssCard.code_hash == hash_code(code)))
    if card is None or card.revoked_at is not None:
        return CardCheck(CardOutcome.INVALID)
    member = session.get(Member, card.member_id)
    if member.expelled_at or member.sss_ended_at:
        return CardCheck(CardOutcome.INVALID)
    audit.record(session, actor_type=PUBLIC.audit_type, actor_id=None, action="sss_card.verify",
                 entity_type="sss_card", entity_id=str(card.id))
    outcome = CardOutcome.VALID if card.year == date.today().year else CardOutcome.OTHER_YEAR
    return CardCheck(outcome, card.year)
