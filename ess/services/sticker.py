"""Yearly sticker of the eCP (R45): design, preview and publication by an administrator.

Cycle: the sticker of the due year (the latest year of the payment period, R27) can be designed while it is
not published. Publishing locks it until the next year and opens paying the fee through the eCP for that
year (payment links are sent to all passes). Without an open sticker only the current image is shown.
"""

import secrets
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from ess import audit
from ess.services import settings
from ess.services.access import Actor, DomainError, require_admin
from ess.stickers import check_template, default_template, generate_sticker


@dataclass
class StickerSettings:
    text_color: str
    bg_color: str
    template: str  # object name, "" = built-in
    url: str  # last published sticker
    year: int | None


def current(session: Session) -> StickerSettings:
    year = settings.get_setting(session, "sticker_year")
    return StickerSettings(settings.get_setting(session, "sticker_text_color") or "#FFFFFF",
                           settings.get_setting(session, "sticker_bg_color") or "transparent",
                           settings.get_setting(session, "sticker_template") or "",
                           settings.get_setting(session, "sticker_url") or "", int(year) if year else None)


def hero_url(session: Session, year: int | None = None) -> str | None:
    """Sticker for the pass: only the one made for the given (current) year."""
    year = year or date.today().year
    url = settings.get_setting(session, f"sticker_url_{year}")
    if url:
        return url
    s = current(session)  # deployed before stickers were kept per year
    return s.url if s.url and s.year == year else None


def due_year(session: Session, today: date | None = None) -> int:
    from ess.services import payments

    return max(payments.payment_years(session, today))


def is_published(session: Session, year: int) -> bool:
    return hero_url(session, year) is not None


def edit_year(session: Session, today: date | None = None) -> int | None:
    """The year whose sticker can be designed now; None when the due year's sticker is published (locked)."""
    year = due_year(session, today)
    return None if is_published(session, year) else year


def _require_open(session: Session, actor: Actor, year: int | None = None) -> int:
    require_admin(actor)
    open_year = edit_year(session)
    if open_year is None:
        raise DomainError("sticker_locked")
    if year is not None and year != open_year:
        raise DomainError("sticker_wrong_year")
    return open_year


def _template(session: Session, store) -> bytes:
    name = current(session).template
    return store.get(name) if name and store else default_template()


def render(session: Session, actor: Actor, store, year: int, text_color: str, bg_color: str, seed: int) -> bytes:
    _require_open(session, actor, year)
    settings.set_setting(session, actor, "sticker_text_color", text_color)  # validates the colours
    settings.set_setting(session, actor, "sticker_bg_color", bg_color)
    s = current(session)
    return generate_sticker(_template(session, store), year, s.text_color, s.bg_color, seed)


def publish(session: Session, actor: Actor, store, year: int, text_color: str, bg_color: str, seed: int) -> str:
    """Generate the sticker (same seed as the preview), publish it and open paying through the eCP."""
    from ess.services import ecp_content

    if store is None:
        raise DomainError("media_store_not_configured")
    png = render(session, actor, store, year, text_color, bg_color, seed)
    url = store.put(f"stickers/{year}-{secrets.token_hex(16)}.png", png, "image/png")
    settings.set_setting(session, actor, "sticker_url", url)
    settings.set_setting(session, actor, "sticker_year", str(year))
    settings.set_setting(session, actor, f"sticker_url_{year}", url)  # passes paid for that year use it
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="sticker.publish",
                 entity_type="setting", entity_id="sticker_url", details={"year": year})
    ecp_content.publish_payment_links(session, actor)  # new sticker and payment link in every eCP
    return url


def upload_template(session: Session, actor: Actor, store, data: bytes) -> None:
    _require_open(session, actor)
    if store is None:
        raise DomainError("media_store_not_configured")
    png = check_template(data)
    name = f"static/sticker-template-{secrets.token_hex(16)}.png"
    store.put(name, png, "image/png")
    settings.set_setting(session, actor, "sticker_template", name)
