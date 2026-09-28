"""Clubs, certificates and documents services (need a PostgreSQL test database)."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from ess.models import CertificateType, Club
from ess.services import certificates, clubs, documents, members
from ess.services.access import Actor, DomainError, PermissionDenied
from ess.services.members import MemberData

pytestmark = pytest.mark.db

ADMIN = Actor(kind="admin", id="admin-1")
SYS_ADMIN = Actor(kind="system_admin", id="sys-1")
MEMBER = Actor(kind="member", id=str(uuid.uuid4()))


def test_clubs(session):
    club = clubs.create_club(session, ADMIN, "  JS   Nová ", "JS N", True)
    assert club.name == "JS Nová"
    with pytest.raises(DomainError, match="club_name_in_use"):
        clubs.create_club(session, ADMIN, "JS Nová", "", True)
    with pytest.raises(PermissionDenied):
        clubs.create_club(session, MEMBER, "JS Iná", "", True)
    clubs.update_club(session, ADMIN, club.id, "JS Nová 2", "N2", False, False)
    assert (club.name, club.uses_candidates, club.active) == ("JS Nová 2", False, False)
    unaffiliated = session.scalars(select(Club).where(Club.is_unaffiliated)).one()
    with pytest.raises(DomainError, match="unaffiliated_club_cannot_be_deactivated"):
        clubs.update_club(session, ADMIN, unaffiliated.id, unaffiliated.name, "SSS", False, False)


def test_certificates(session):
    m = members.create_member(session, ADMIN, MemberData("Ján", "Novák"))
    srt1 = session.scalars(select(CertificateType).where(CertificateType.code == "srt1")).one()
    with pytest.raises(DomainError, match="invalid_period"):
        certificates.add_certificate(session, ADMIN, m.id, srt1.id, date(2026, 1, 1), date(2025, 1, 1))
    cert = certificates.add_certificate(session, ADMIN, m.id, srt1.id, date(2024, 1, 1), None, "kurz")
    certificates.remove_certificate(session, ADMIN, cert.id)
    with pytest.raises(PermissionDenied):
        certificates.add_certificate_type(session, ADMIN, "speleo_diver", "Jaskynný potápač")
    certificates.add_certificate_type(session, SYS_ADMIN, "Speleo_Diver", "Jaskynný potápač")
    with pytest.raises(DomainError, match="certificate_type_exists"):
        certificates.add_certificate_type(session, SYS_ADMIN, "speleo_diver", "X")
    assert "Jaskynný potápač" in [t.name for t in certificates.active_types(session)]


def test_documents(session):
    with pytest.raises(DomainError, match="url_must_be_https"):
        documents.save_document(session, ADMIN, "Stanovy", "http://example.org/s.pdf", None)
    current = documents.save_document(session, ADMIN, "Stanovy", "https://example.org/s.pdf", None)
    documents.save_document(session, ADMIN, "Stará výnimka", "https://example.org/v.pdf", date(2020, 1, 1))
    assert [d.title for d in documents.valid_documents(session)] == ["Stanovy"]
    assert len(documents.all_documents(session)) == 2
    documents.save_document(session, ADMIN, "Stanovy SSS", "https://example.org/s2.pdf", None, 1, current.id)
    assert current.title == "Stanovy SSS"
    documents.delete_document(session, ADMIN, current.id)
    assert [d.title for d in documents.all_documents(session)] == ["Stará výnimka"]


def test_club_logo_url(session):
    club = clubs.create_club(session, ADMIN, "JS Logo", "", True, logo_url="https://storage.googleapis.com/b/club_logos/a.png")
    assert club.logo_url.endswith("a.png")
    with pytest.raises(DomainError, match="url_must_be_https"):
        clubs.update_club(session, ADMIN, club.id, "JS Logo", "", True, True, logo_url="http://x/a.png")
    clubs.update_club(session, ADMIN, club.id, "JS Logo", "", True, True, logo_url="")
    assert club.logo_url is None
