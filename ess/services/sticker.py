"""Yearly sticker of the eCP (system administrators): template, preview and deployment."""

import secrets
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from ess import audit
from ess.services import settings
from ess.services.access import Actor, DomainError, require_system_admin
from ess.stickers import check_template, default_template, generate_sticker


@dataclass
class StickerSettings:
    text_color: str
    bg_color: str
    template: str  # object name, "" = built-in
    url: str
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


def _template(session: Session, store) -> bytes:
    name = current(session).template
    return store.get(name) if name and store else default_template()


def render(session: Session, actor: Actor, store, year: int, text_color: str, bg_color: str, seed: int) -> bytes:
    require_system_admin(actor)
    if not (date.today().year - 1 <= year <= date.today().year + 1):
        raise DomainError("invalid_card_year")
    settings.set_setting(session, actor, "sticker_text_color", text_color)  # validates the colours
    settings.set_setting(session, actor, "sticker_bg_color", bg_color)
    s = current(session)
    return generate_sticker(_template(session, store), year, s.text_color, s.bg_color, seed)


def deploy(session: Session, actor: Actor, store, year: int, text_color: str, bg_color: str, seed: int) -> str:
    """Generate the sticker (same seed as the preview) and publish it for new and updated passes."""
    if store is None:
        raise DomainError("media_store_not_configured")
    png = render(session, actor, store, year, text_color, bg_color, seed)
    url = store.put(f"stickers/{year}-{secrets.token_hex(16)}.png", png, "image/png")
    settings.set_setting(session, actor, "sticker_url", url)
    settings.set_setting(session, actor, "sticker_year", str(year))
    settings.set_setting(session, actor, f"sticker_url_{year}", url)  # passes paid for that year use it
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="sticker.deploy",
                 entity_type="setting", entity_id="sticker_url", details={"year": year})
    return url


def upload_template(session: Session, actor: Actor, store, data: bytes) -> None:
    require_system_admin(actor)
    if store is None:
        raise DomainError("media_store_not_configured")
    png = check_template(data)
    name = f"static/sticker-template-{secrets.token_hex(16)}.png"
    store.put(name, png, "image/png")
    settings.set_setting(session, actor, "sticker_template", name)
