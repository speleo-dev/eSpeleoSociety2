"""Kartička SSS: one card per member and calendar year, with its own random code (R31–R33).

- The first card is issued once, manually, by the club chair or an administrator (when the member is
  added or becomes a member of SSS) – for this year, or for the next year during the payment period.
- Later years: the card is e-mailed automatically when the fee is marked as paid (phase 3).
- The same card can be downloaded or sent again; a new one only as a replacement of a lost, stolen or
  damaged card, and only by an administrator – the old code then shows that state.
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
from ess.security import pii
from ess.services import members, payments
from ess.services.access import PUBLIC, Actor, DomainError, PermissionDenied, can_manage_club, require_admin

REPLACE_REASONS = ("lost", "stolen", "damaged")
FORMATS = ("pdf", "png")
_CTX = "sss_cards.code"


def hash_code(code: str) -> bytes:
    return hashlib.sha256(code.encode("ascii", errors="ignore")).digest()


@dataclass
class IssuedCard:
    card: SssCard
    content: CardContent
    email: str | None
    first_name: str
    card_format: str = "pdf"  # the member's preferred format


def current_card(session: Session, member_id: uuid.UUID, year: int) -> SssCard | None:
    return session.scalar(select(SssCard).where(SssCard.member_id == member_id, SssCard.year == year,
                                                SssCard.revoked_at.is_(None)))


def _member_for_card(session: Session, member_id: uuid.UUID) -> Member:
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if member.expelled_at or member.sss_ended_at:
        raise DomainError("member_not_in_sss")
    return member


def _content(session: Session, member: Member, card: SssCard, code: str, base_url: str) -> IssuedCard:
    data = members.read_member(member)
    club = session.scalar(select(Club).join(Membership, Membership.club_id == Club.id).where(
        Membership.member_id == member.id, Membership.valid_to.is_(None), Membership.is_primary))
    content = CardContent(full_name=data.full_name(), club_name=club.name if club else "",
                          card_number=data.card_number, year=card.year,
                          verify_url=f"{base_url.rstrip('/')}/k/{code}")
    return IssuedCard(card, content, data.email, data.first_name, member.card_format or "pdf")


def _new_card(session: Session, actor: Actor, member: Member, year: int, base_url: str) -> IssuedCard:
    code = secrets.token_urlsafe(18)
    card = SssCard(id=uuid.uuid4(), member_id=member.id, year=year, code_hash=hash_code(code),
                   code_enc=pii.encrypt(code, _CTX), issued_by=actor.id)
    session.add(card)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="sss_card.issue",
                 entity_type="sss_card", entity_id=str(card.id), details={"year": year})
    return _content(session, member, card, code, base_url)


def allowed_years(session: Session, today: date | None = None) -> list[int]:
    """This year; the next year too during the payment period (R27, R33)."""
    return payments.payment_years(session, today)


def can_issue(session: Session, member_id: uuid.UUID, year: int) -> bool:
    """A card of the year was never issued (a replaced card counts as issued)."""
    return session.scalar(select(SssCard.id).where(SssCard.member_id == member_id, SssCard.year == year)) is None


def issue(session: Session, actor: Actor, member_id: uuid.UUID, year: int, base_url: str,
          card_format: str = "pdf") -> IssuedCard:
    """First card of the year, once – by the chair of the member's club or an administrator."""
    if card_format not in FORMATS:
        raise DomainError("invalid_value")
    member = _member_for_card(session, member_id)
    clubs = session.scalars(select(Club).join(Membership, Membership.club_id == Club.id).where(
        Membership.member_id == member_id, Membership.valid_to.is_(None))).all()
    if not actor.is_admin and not any(can_manage_club(session, actor, c) for c in clubs):
        raise PermissionDenied("club_manager")
    if year not in allowed_years(session):
        raise DomainError("invalid_card_year")
    if not can_issue(session, member_id, year):
        raise DomainError("card_already_issued")
    member.card_format = card_format  # the member receives cards (next years automatically after payment)
    return _new_card(session, actor, member, year, base_url)


def again(session: Session, actor: Actor, card_id: uuid.UUID, base_url: str) -> IssuedCard:
    """The same card (same QR code) for download or e-mail again."""
    require_admin(actor)
    card = session.get(SssCard, card_id)
    if card is None or card.revoked_at is not None or card.code_enc is None:
        raise DomainError("card_not_available")
    member = _member_for_card(session, card.member_id)
    return _content(session, member, card, pii.decrypt(card.code_enc, _CTX), base_url)


def replace(session: Session, actor: Actor, card_id: uuid.UUID, reason: str, base_url: str) -> IssuedCard:
    """The card was lost, stolen or damaged: the old code stops working (and says why), a new card is issued."""
    require_admin(actor)
    if reason not in REPLACE_REASONS:
        raise DomainError("invalid_value")
    card = session.get(SssCard, card_id)
    if card is None or card.revoked_at is not None:
        raise DomainError("card_not_available")
    member = _member_for_card(session, card.member_id)
    card.revoked_at, card.revoke_reason = datetime.now(UTC), reason
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="sss_card.revoke",
                 entity_type="sss_card", entity_id=str(card.id), details={"reason": reason})
    session.flush()
    return _new_card(session, actor, member, card.year, base_url)


class CardOutcome(str, enum.Enum):
    VALID = "valid"
    OTHER_YEAR = "other_year"  # a card for a past (or future) year
    LOST = "lost"
    STOLEN = "stolen"
    REPLACED = "damaged"  # replaced by a new card
    INVALID = "invalid"  # unknown code, or the holder is no longer a member of SSS


@dataclass
class CardCheck:
    outcome: CardOutcome
    year: int | None = None


def verify(session: Session, code: str) -> CardCheck:
    card = session.scalar(select(SssCard).where(SssCard.code_hash == hash_code(code)))
    if card is None:
        return CardCheck(CardOutcome.INVALID)
    if card.revoked_at is not None:
        reason = card.revoke_reason if card.revoke_reason in REPLACE_REASONS else None
        return CardCheck(CardOutcome(reason) if reason else CardOutcome.INVALID, card.year)
    member = session.get(Member, card.member_id)
    if member.expelled_at or member.sss_ended_at:
        return CardCheck(CardOutcome.INVALID)
    audit.record(session, actor_type=PUBLIC.audit_type, actor_id=None, action="sss_card.verify",
                 entity_type="sss_card", entity_id=str(card.id))
    outcome = CardOutcome.VALID if card.year == date.today().year else CardOutcome.OTHER_YEAR
    return CardCheck(outcome, card.year)
