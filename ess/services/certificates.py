"""Member certificates (SRT1, SRT2, rescuer, firefighter, ...)."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import CertificateType, Member, MemberCertificate
from ess.services.access import Actor, DomainError, require_admin, require_system_admin


def add_certificate(
    session: Session,
    actor: Actor,
    member_id: uuid.UUID,
    certificate_type_id: uuid.UUID,
    valid_from: date | None = None,
    valid_to: date | None = None,
    note: str = "",
) -> MemberCertificate:
    require_admin(actor)
    if session.get(Member, member_id) is None:
        raise DomainError("member_not_found")
    cert_type = session.get(CertificateType, certificate_type_id)
    if cert_type is None or not cert_type.active:
        raise DomainError("certificate_type_not_found")
    if valid_from and valid_to and valid_to < valid_from:
        raise DomainError("invalid_period")
    cert = MemberCertificate(id=uuid.uuid4(), member_id=member_id, certificate_type_id=certificate_type_id,
                             valid_from=valid_from, valid_to=valid_to, note=note.strip() or None)
    session.add(cert)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="certificate.add",
                 entity_type="member_certificate", entity_id=str(cert.id),
                 details={"member_id": str(member_id), "type": cert_type.code})
    return cert


def remove_certificate(session: Session, actor: Actor, certificate_id: uuid.UUID) -> None:
    """Remove a certificate entered by mistake (an expired certificate keeps its record with valid_to)."""
    require_admin(actor)
    cert = session.get(MemberCertificate, certificate_id)
    if cert is None:
        raise DomainError("certificate_not_found")
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="certificate.remove",
                 entity_type="member_certificate", entity_id=str(cert.id), details={"member_id": str(cert.member_id)})
    session.delete(cert)
    session.flush()


def add_certificate_type(session: Session, actor: Actor, code: str, name: str) -> CertificateType:
    require_admin(actor)  # R44: administrators maintain the certificate types
    code = code.strip().lower()
    if not code or not name.strip():
        raise DomainError("name_required")
    if session.scalar(select(CertificateType.id).where(CertificateType.code == code)):
        raise DomainError("certificate_type_exists")
    cert_type = CertificateType(id=uuid.uuid4(), code=code, name=name.strip(), active=True)
    session.add(cert_type)
    session.flush()
    audit.record(session, actor_type=actor.audit_type, actor_id=actor.id, action="certificate_type.add",
                 entity_type="certificate_type", entity_id=str(cert_type.id))
    return cert_type


def active_types(session: Session) -> list[CertificateType]:
    return list(session.scalars(select(CertificateType).where(CertificateType.active).order_by(CertificateType.name)))
