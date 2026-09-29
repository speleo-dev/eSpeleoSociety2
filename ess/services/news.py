"""News for members, written by administrators and shown on the portal."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import News
from ess.services.access import Actor, DomainError, require_admin


def save(session: Session, actor: Actor, title: str, body: str, published_on: date | None = None,
         visible: bool = True, news_id: uuid.UUID | None = None) -> News:
    require_admin(actor)
    title, body = " ".join(title.split()), body.strip().replace("\r\n", "\n")
    if not title or not body:
        raise DomainError("news_required")
    item = session.get(News, news_id) if news_id else None
    if news_id and item is None:
        raise DomainError("news_not_found")
    if item is None:
        item = News(id=uuid.uuid4(), created_by=actor.id)
        session.add(item)
    item.title, item.body = title[:200], body[:20000]
    item.published_on, item.visible = published_on or date.today(), visible
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id,
                 action="news.update" if news_id else "news.create", entity_type="news", entity_id=str(item.id))
    return item


def delete(session: Session, actor: Actor, news_id: uuid.UUID) -> None:
    require_admin(actor)
    item = session.get(News, news_id)
    if item is None:
        raise DomainError("news_not_found")
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="news.delete",
                 entity_type="news", entity_id=str(item.id))
    session.delete(item)


def all_news(session: Session) -> list[News]:
    return list(session.scalars(select(News).order_by(News.published_on.desc(), News.created_at.desc())))


def published(session: Session, limit: int | None = None, on: date | None = None) -> list[News]:
    """Visible news up to today (a later date = scheduled), newest first."""
    query = (select(News).where(News.visible.is_(True), News.published_on <= (on or date.today()))
             .order_by(News.published_on.desc(), News.created_at.desc()))
    return list(session.scalars(query.limit(limit) if limit else query))

