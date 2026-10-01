"""Documents shown on the portal and verification page (title, validity, link)."""

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import Document
from ess.services.access import Actor, DomainError, require_staff


def _validate(title: str, url: str) -> tuple[str, str]:
    title, url = title.strip(), url.strip()
    if not title:
        raise DomainError("name_required")
    if not url.startswith("https://"):
        raise DomainError("url_must_be_https")
    return title, url


def save_document(
    session: Session, actor: Actor, title: str, url: str, valid_until: date | None, sort_order: int = 0,
    document_id: uuid.UUID | None = None,
) -> Document:
    require_staff(actor)
    title, url = _validate(title, url)
    doc = session.get(Document, document_id) if document_id else None
    if document_id and doc is None:
        raise DomainError("document_not_found")
    if doc is None:
        doc = Document(id=uuid.uuid4())
        session.add(doc)
    doc.title, doc.url, doc.valid_until, doc.sort_order = title, url, valid_until, sort_order
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id,
                 action="document.update" if document_id else "document.create",
                 entity_type="document", entity_id=str(doc.id))
    return doc


def delete_document(session: Session, actor: Actor, document_id: uuid.UUID) -> None:
    require_staff(actor)
    doc = session.get(Document, document_id)
    if doc is None:
        raise DomainError("document_not_found")
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="document.delete",
                 entity_type="document", entity_id=str(doc.id))
    session.delete(doc)
    session.flush()


def all_documents(session: Session) -> list[Document]:
    return list(session.scalars(select(Document).order_by(Document.sort_order, Document.title)))


def valid_documents(session: Session, on: date | None = None) -> list[Document]:
    """Documents shown publicly: expired ones are hidden."""
    on = on or date.today()
    return list(session.scalars(
        select(Document).where(or_(Document.valid_until.is_(None), Document.valid_until >= on))
        .order_by(Document.sort_order, Document.title)
    ))
