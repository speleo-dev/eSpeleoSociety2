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
    "renewal_window_days": int,  # payment link for the next year appears this many days before year end
    # eCP (phase 2): positive whole numbers
    "ecp_link_valid_hours": int,  # validity of one-time links in e-mails
    "ecp_application_expiry_days": int,  # unfinished application expires after
    "ecp_qr_grace_minutes": int,  # a used QR token stays valid for
    "ecp_qr_daily_limit": int,  # new QR codes per eCP and day
}

# Built-in defaults (also inserted by migrations 0008 and 0009).
DEFAULTS = {
    "renewal_window_days": "60",
    "ecp_link_valid_hours": "24",
    "ecp_application_expiry_days": "14",
    "ecp_qr_grace_minutes": "15",
    "ecp_qr_daily_limit": "10",
}


def get_setting(session: Session, key: str) -> str | None:
    setting = session.get(Setting, key)
    return setting.value if setting else DEFAULTS.get(key)


def get_int(session: Session, key: str) -> int:
    return int(get_setting(session, key) or DEFAULTS[key])


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
    if key.startswith("ecp_") and parsed < 1:
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
