"""Application settings stored in the database (fee amounts etc.). Changed by system administrators."""

from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from ess import audit
from ess.models import Setting
from ess.services.access import Actor, DomainError, require_system_admin

# key -> validator
_KNOWN: dict[str, type] = {
    "fee_amount": Decimal,
    "reduced_fee_amount": Decimal,
    "reduced_fee_age": int,
    "fee_currency": str,
}


def get_setting(session: Session, key: str) -> str | None:
    setting = session.get(Setting, key)
    return setting.value if setting else None


def set_setting(session: Session, actor: Actor, key: str, value: str) -> None:
    require_system_admin(actor)
    kind = _KNOWN.get(key)
    if kind is None:
        raise DomainError("unknown_setting")
    try:
        parsed = kind(value.strip())
    except (InvalidOperation, ValueError):
        raise DomainError("invalid_value") from None
    if kind in (Decimal, int) and parsed < 0:
        raise DomainError("invalid_value")
    setting = session.get(Setting, key)
    old = setting.value if setting else None
    if setting is None:
        setting = Setting(key=key, value=str(parsed))
        session.add(setting)
    else:
        setting.value = str(parsed)
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="setting.update",
                 entity_type="setting", entity_id=key, details={"old": old, "new": str(parsed)})
