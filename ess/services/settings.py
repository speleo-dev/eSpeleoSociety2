"""Application settings stored in the database (fee amounts etc.). Changed by system administrators."""

import re
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from ess import audit
from ess.models import Setting
from ess.services.access import Actor, DomainError, require_admin, require_staff

def _colour(value: str) -> str:
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise ValueError(value)
    return value.upper()


def _iban(value: str) -> str:
    """Empty (not configured yet) or a valid IBAN (ISO 13616 check digits)."""
    iban = "".join(value.split()).upper()
    if not iban:
        return ""
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}", iban):
        raise ValueError(value)
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    if int(digits) % 97 != 1:
        raise ValueError(value)
    return iban


def _background(value: str) -> str:
    return "transparent" if value.lower() == "transparent" else _colour(value)


# key -> validator
_KNOWN: dict[str, type] = {
    "fee_amount": Decimal,
    "reduced_fee_amount": Decimal,
    "reduced_fee_age": int,
    "fee_currency": str,
    "payment_iban": _iban,  # account for membership fees (PAYMe link)
    "payment_account_name": str,  # beneficiary name in the PAYMe link
    "renewal_window_days": int,  # payment link for the next year appears this many days before year end
    # eCP (phase 2): positive whole numbers
    "ecp_link_valid_hours": int,  # validity of one-time links in e-mails
    "ecp_application_expiry_days": int,  # unfinished application expires after
    "ecp_qr_grace_minutes": int,  # a used QR token stays valid for
    "ecp_qr_daily_limit": int,  # new QR codes per eCP and day
    "portal_max_devices": int,  # signed-in devices per member on the portal (R40)
    # yearly sticker (hero image of the eCP)
    "sticker_text_color": _colour,
    "sticker_bg_color": _background,
    "sticker_template": str,  # object name of an uploaded template ("" = built-in)
    "sticker_url": str,  # public URL of the deployed sticker
    "sticker_year": int,
}

# Fee and payment settings: the administrator only (R50); eCP and portal settings: administrator or superadmin.
# The yearly sticker (`sticker_*`) is changed by administrators only through `sticker` (yearly lock, R45).
ADMIN_KEYS = {"fee_amount", "reduced_fee_amount", "reduced_fee_age", "fee_currency", "renewal_window_days",
              "payment_iban", "payment_account_name"}

# Built-in defaults (also inserted by migrations 0008, 0009, 0013 and 0019).
DEFAULTS = {
    "sticker_text_color": "#FFFFFF",
    "sticker_bg_color": "transparent",
    "renewal_window_days": "60",
    "payment_iban": "",
    "payment_account_name": "Slovenská speleologická spoločnosť",
    "ecp_link_valid_hours": "24",
    "ecp_application_expiry_days": "14",
    "ecp_qr_grace_minutes": "15",
    "ecp_qr_daily_limit": "10",
    "portal_max_devices": "2",
}


def get_setting(session: Session, key: str) -> str | None:
    setting = session.get(Setting, key)
    return setting.value if setting else DEFAULTS.get(key)


def get_int(session: Session, key: str) -> int:
    return int(get_setting(session, key) or DEFAULTS[key])


def set_setting(session: Session, actor: Actor, key: str, value: str) -> None:
    if key in ADMIN_KEYS or key.startswith("sticker_"):
        require_admin(actor)  # fees, payment account, sticker: the administrator only (R50)
    else:
        require_staff(actor)  # eCP and portal settings: administrator or superadmin
    kind = _KNOWN.get(key) or (str if re.fullmatch(r"sticker_url_\d{4}", key) else None)  # sticker of a year
    if kind is None:
        raise DomainError("unknown_setting")
    try:
        parsed = kind(value.strip())
    except (InvalidOperation, ValueError):
        raise DomainError("invalid_value") from None
    if kind in (Decimal, int) and parsed < 0:
        raise DomainError("invalid_value")
    if key.startswith(("ecp_", "portal_")) and parsed < 1:
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
