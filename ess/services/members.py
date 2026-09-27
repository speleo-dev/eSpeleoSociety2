"""Members: encrypted personal data, lookup and expulsion."""

import enum
import uuid
from dataclasses import dataclass, fields
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Club, Member, Membership, MembershipEndReason, MembershipStatus, PositionHolder
from ess.security import pii
from ess.services.access import Actor, DomainError, PermissionDenied, chaired_club_ids, require_admin

# Encryption contexts (associated data) - one per column.
_CTX = {
    "first_name": "members.first_name",
    "last_name": "members.last_name",
    "title_before": "members.title_before",
    "title_after": "members.title_after",
    "email": "members.email",
    "address": "members.address",
    "phone": "members.phone",
    "card_number": "members.card_number",
}
_CTX_BIRTH_DATE = "members.birth_date"
_BIDX_LOOKUP = "members.lookup"
_BIDX_EMAIL = "members.email"
_BIDX_CARD = "members.card_number"


@dataclass
class MemberData:
    """Plaintext view of a member. Exists only in memory, never logged."""

    first_name: str
    last_name: str
    title_before: str | None = None
    title_after: str | None = None
    birth_date: date | None = None
    email: str | None = None
    address: str | None = None
    phone: str | None = None
    card_number: str | None = None
    member_since: date | None = None
    reduced_fee: bool = False

    def full_name(self) -> str:
        name = " ".join(p for p in (self.title_before, self.first_name, self.last_name) if p)
        return f"{name}, {self.title_after}" if self.title_after else name


def lookup_index(first_name: str, last_name: str, birth_year: int) -> bytes | None:
    """Blind index used to find a member from an eCP request (first name, last name, birth year)."""
    return pii.blind_index(_BIDX_LOOKUP, first_name, last_name, str(birth_year))


def email_index(email: str | None) -> bytes | None:
    return pii.blind_index(_BIDX_EMAIL, email.strip() if email else email)


def _validate(data: MemberData) -> None:
    if not data.first_name.strip() or not data.last_name.strip():
        raise DomainError("name_required")
    if data.email and "@" not in data.email:
        raise DomainError("invalid_email")


def _apply(member: Member, data: MemberData) -> None:
    for name, ctx in _CTX.items():
        value = getattr(data, name)
        setattr(member, f"{name}_enc", pii.encrypt(value.strip() if value else value, ctx))
    member.birth_date_enc = pii.encrypt_date(data.birth_date, _CTX_BIRTH_DATE)
    member.lookup_bidx = (
        lookup_index(data.first_name, data.last_name, data.birth_date.year) if data.birth_date else None
    )
    member.email_bidx = email_index(data.email)
    member.card_number_bidx = pii.blind_index(_BIDX_CARD, data.card_number)
    member.member_since = data.member_since
    member.reduced_fee = data.reduced_fee


def read_member(member: Member) -> MemberData:
    values = {name: pii.decrypt(getattr(member, f"{name}_enc"), ctx) for name, ctx in _CTX.items()}
    return MemberData(
        **values,
        birth_date=pii.decrypt_date(member.birth_date_enc, _CTX_BIRTH_DATE),
        member_since=member.member_since,
        reduced_fee=member.reduced_fee,
    )


def _check_unique(session: Session, member: Member) -> None:
    for column, code in ((Member.email_bidx, "email_in_use"), (Member.card_number_bidx, "card_number_in_use")):
        value = getattr(member, column.key)
        if value is None:
            continue
        other = session.scalar(select(Member.id).where(column == value, Member.id != member.id))
        if other:
            raise DomainError(code)


def create_member(session: Session, actor: Actor, data: MemberData) -> Member:
    """Create a member record. Club chairs create members through `memberships.add_new_member_to_club`."""
    require_admin(actor)
    return _create(session, actor, data)


def _create(session: Session, actor: Actor, data: MemberData) -> Member:
    _validate(data)
    member = Member(id=uuid.uuid4())
    _apply(member, data)
    _check_unique(session, member)
    session.add(member)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="member.create",
                 entity_type="member", entity_id=str(member.id))
    return member


def _can_edit(session: Session, actor: Actor, member: Member) -> bool:
    if actor.is_admin:
        return True
    if actor.kind != "member":
        return False
    chaired = chaired_club_ids(session, uuid.UUID(actor.id))
    return any(m.valid_to is None and m.club_id in chaired for m in member.memberships)


def update_member(session: Session, actor: Actor, member_id: uuid.UUID, data: MemberData) -> Member:
    """Update personal data. Allowed for admins and the chair of a club the member belongs to."""
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if not _can_edit(session, actor, member):
        raise PermissionDenied("member_edit")
    if data.reduced_fee != member.reduced_fee and not actor.is_admin:
        raise PermissionDenied("reduced_fee")
    before = read_member(member)
    _validate(data)
    _apply(member, data)
    _check_unique(session, member)
    changed = sorted(f.name for f in fields(MemberData) if getattr(before, f.name) != getattr(data, f.name))
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="member.update",
                 entity_type="member", entity_id=str(member.id), details={"fields": changed})
    return member


def find_by_lookup(session: Session, first_name: str, last_name: str, birth_year: int) -> list[Member]:
    index = lookup_index(first_name, last_name, birth_year)
    if index is None:
        return []
    return list(session.scalars(select(Member).where(Member.lookup_bidx == index)))


def expel_member(session: Session, actor: Actor, member_id: uuid.UUID, reason: str, on: date | None = None) -> None:
    """Expel from SSS (decision of the general assembly). Ends all memberships and positions."""
    require_admin(actor)
    on = on or date.today()
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if member.expelled_at:
        raise DomainError("already_expelled")
    if not reason.strip():
        raise DomainError("reason_required")
    member.expelled_at = on
    member.expelled_reason = reason.strip()
    for membership in session.scalars(
        select(Membership).where(Membership.member_id == member_id, Membership.valid_to.is_(None))
    ):
        membership.valid_to = on
        membership.end_reason = MembershipEndReason.EXPELLED
        membership.is_primary = False
    for holder in session.scalars(
        select(PositionHolder).where(PositionHolder.member_id == member_id, PositionHolder.valid_to.is_(None))
    ):
        holder.valid_to = on
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="member.expel",
                 entity_type="member", entity_id=str(member_id))


def apply_age_reduced_fee(session: Session, actor: Actor, fee_year: int, age: int) -> int:
    """R13: a member who reaches `age` in year X gets the reduced fee from year X+1. Never unsets the flag.

    Returns the number of members newly flagged.
    """
    require_admin(actor)
    count = 0
    for member in session.scalars(
        select(Member).where(Member.reduced_fee.is_(False), Member.birth_date_enc.is_not(None))
    ):
        birth_date = pii.decrypt_date(member.birth_date_enc, _CTX_BIRTH_DATE)
        if birth_date and birth_date.year + age <= fee_year - 1:
            member.reduced_fee = True
            count += 1
            audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="member.reduced_fee_auto",
                         entity_type="member", entity_id=str(member.id), details={"fee_year": fee_year})
    return count


# --- SSS membership (as opposed to membership in a club) ------------------------------------------

class SssStatus(str, enum.Enum):
    MEMBER = "member"  # has at least one open club membership (incl. "SSS - nezaradení")
    AWAITING_DECISION = "awaiting_decision"  # left all clubs; presidium decides about SSS membership
    ENDED = "ended"  # SSS membership ended by decision; can be restored
    EXPELLED = "expelled"  # expelled by the general assembly; cannot be restored
    NEVER = "never"  # no membership at all yet


def sss_status(session: Session, member: Member) -> SssStatus:
    if member.expelled_at:
        return SssStatus.EXPELLED
    has_open = session.scalar(
        select(exists().where(Membership.member_id == member.id, Membership.valid_to.is_(None)))
    )
    if has_open:
        return SssStatus.MEMBER
    if member.sss_ended_at:
        return SssStatus.ENDED
    had_any = session.scalar(select(exists().where(Membership.member_id == member.id)))
    return SssStatus.AWAITING_DECISION if had_any else SssStatus.NEVER


def awaiting_decision(session: Session) -> list[Member]:
    """Members who left their last club and wait for the presidium's decision about SSS membership."""
    open_exists = exists().where(Membership.member_id == Member.id, Membership.valid_to.is_(None))
    any_exists = exists().where(Membership.member_id == Member.id)
    return list(
        session.scalars(
            select(Member).where(
                Member.expelled_at.is_(None), Member.sss_ended_at.is_(None), ~open_exists, any_exists
            )
        )
    )


def end_sss_membership(session: Session, actor: Actor, member_id: uuid.UUID, note: str, on: date | None = None) -> None:
    """Record the presidium's decision that SSS membership ends (e.g. no longer wants to be a caver).

    Not an expulsion: the member can later be restored. Any remaining club memberships and positions end too.
    """
    require_admin(actor)
    on = on or date.today()
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if member.expelled_at:
        raise DomainError("member_expelled")
    if member.sss_ended_at:
        raise DomainError("sss_membership_already_ended")
    for membership in session.scalars(
        select(Membership).where(Membership.member_id == member_id, Membership.valid_to.is_(None))
    ):
        membership.valid_to = on
        membership.end_reason = MembershipEndReason.TERMINATED
        membership.is_primary = False
    for holder in session.scalars(
        select(PositionHolder).where(PositionHolder.member_id == member_id, PositionHolder.valid_to.is_(None))
    ):
        holder.valid_to = on
    member.sss_ended_at = on
    member.sss_ended_note = note.strip() or None
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="member.sss_end",
                 entity_type="member", entity_id=str(member_id))


def restore_to_unaffiliated(session: Session, actor: Actor, member_id: uuid.UUID, on: date | None = None) -> Membership:
    """The member asked the presidium to be kept / restored as an unaffiliated SSS member."""
    from ess.services import memberships  # avoid circular import

    require_admin(actor)
    member = session.get(Member, member_id)
    if member is None:
        raise DomainError("member_not_found")
    if member.expelled_at:
        raise DomainError("member_expelled")
    unaffiliated = session.scalars(select(Club).where(Club.is_unaffiliated)).one()
    return memberships.add_membership(session, actor, member_id, unaffiliated.id, MembershipStatus.MEMBER, on)
