"""Administration forms: members, clubs, positions, certificates, access, settings, documents."""

import re
import uuid

import pytest
from sqlalchemy import select

from ess.models import CertificateType, Club, Member, Membership, PositionHolder
from ess.services import members
from ess.services.access import SYSTEM
from ess.services.members import MemberData
from tests.test_web_admin import client, csrf, google, login  # noqa: F401  (fixtures and helpers)

pytestmark = pytest.mark.db


def _club(migrated_db, name="JS Formulárová") -> uuid.UUID:
    with migrated_db() as s:
        club = Club(id=uuid.uuid4(), name=name, is_unaffiliated=False, uses_candidates=True, active=True)
        s.add(club)
        s.commit()
        return club.id


def _member_id_from(response) -> uuid.UUID:
    return uuid.UUID(re.search(r"/admin/members/([0-9a-f-]{36})", response.headers["location"]).group(1))


def test_create_and_edit_member(client, google, migrated_db):
    login(client, google)
    club_id = _club(migrated_db)
    form = {"csrf_token": csrf(client), "first_name": "Eva", "last_name": "Hlbočanová", "title_before": "Mgr.",
            "birth_date": "1985-03-04", "email": "eva@example.org", "club_id": str(club_id), "status": "member"}
    response = client.post("/admin/members/new", data=form, follow_redirects=False)
    assert response.status_code == 303
    member_id = _member_id_from(response)
    page = client.get(f"/admin/members/{member_id}").text
    assert "Mgr. Eva Hlbočanová" in page and "Člen bol pridaný." in page and "JS Formulárová" in page

    edit = {"csrf_token": csrf(client), "first_name": "Eva", "last_name": "Hlbočanová", "phone": "+421 900 000 000",
            "reduced_fee": "on"}
    client.post(f"/admin/members/{member_id}/edit", data=edit, follow_redirects=False)
    page = client.get(f"/admin/members/{member_id}").text
    assert "+421 900 000 000" in page and "zľavnené členské" in page
    # Cleared fields are cleared (the edit form always sends all fields).
    assert "eva@example.org" not in page


def test_create_member_errors_keep_values(client, google, migrated_db):
    login(client, google)
    club_id = _club(migrated_db)
    with migrated_db() as s:
        members.create_member(s, SYSTEM, MemberData("Iný", "Člen", card_number="777"))
        s.commit()
    form = {"csrf_token": csrf(client), "first_name": "Nový", "last_name": "Zadávaný", "card_number": "777",
            "club_id": str(club_id)}
    response = client.post("/admin/members/new", data=form)
    assert response.status_code == 400
    assert "Toto číslo preukazu už má iný člen." in response.text and 'value="Zadávaný"' in response.text
    bad_date = client.post("/admin/members/new", data={**form, "card_number": "", "birth_date": "31.12.1980"})
    assert bad_date.status_code == 400 and "Neplatný dátum." in bad_date.text


def test_membership_positions_certificates_and_expulsion(client, google, migrated_db):
    login(client, google)
    a, b = _club(migrated_db, "JS A"), _club(migrated_db, "JS B")
    response = client.post("/admin/members/new", data={
        "csrf_token": csrf(client), "first_name": "Peter", "last_name": "Hrubý", "club_id": str(a)}, follow_redirects=False)
    member_id = _member_id_from(response)
    token = csrf(client)
    client.post(f"/admin/members/{member_id}/memberships", data={"csrf_token": token, "club_id": str(b)})
    client.post(f"/admin/members/{member_id}/positions",
                data={"csrf_token": token, "position_code": "club_chair", "club_id": str(a)})
    with migrated_db() as s:
        cert_type = s.scalars(select(CertificateType).where(CertificateType.code == "srt2")).one()
        second = s.scalars(select(Membership).where(Membership.member_id == member_id, Membership.club_id == b)).one()
    client.post(f"/admin/members/{member_id}/certificates",
                data={"csrf_token": token, "certificate_type_id": str(cert_type.id), "valid_from": "2025-05-01"})
    client.post(f"/admin/memberships/{second.id}/primary", data={"csrf_token": token,
                                                                 "back": f"/admin/members/{member_id}"})
    page = client.get(f"/admin/members/{member_id}").text
    assert "Predseda skupiny" in page and "SRT2" in page
    assert "Peter Hrubý" in client.get("/admin/organization").text

    client.post(f"/admin/members/{member_id}/expel", data={"csrf_token": token, "reason": "Uznesenie VZ 3/2026"})
    with migrated_db() as s:
        assert s.get(Member, member_id).expelled_at is not None
        assert s.scalars(select(PositionHolder).where(PositionHolder.valid_to.is_(None))).all() == []


def test_club_create_edit_and_chair(client, google, migrated_db):
    login(client, google)
    response = client.post("/admin/clubs/new", data={"csrf_token": csrf(client), "name": "JS Nová",
                                                     "uses_candidates": "on"}, follow_redirects=False)
    club_id = response.headers["location"].rsplit("/", 1)[1]
    assert "JS Nová" in client.get("/admin/clubs").text
    dup = client.post("/admin/clubs/new", data={"csrf_token": csrf(client), "name": "JS Nová"})
    assert dup.status_code == 400 and "Skupina s týmto názvom už existuje." in dup.text

    response = client.post("/admin/members/new", data={
        "csrf_token": csrf(client), "first_name": "Jana", "last_name": "Predsedová", "club_id": club_id},
        follow_redirects=False)
    member_id = _member_id_from(response)
    client.post("/admin/positions", data={"csrf_token": csrf(client), "member_id": str(member_id),
                                          "position_code": "club_chair", "club_id": club_id,
                                          "back": f"/admin/clubs/{club_id}"})
    assert "Jana Predsedová" in client.get(f"/admin/clubs/{club_id}").text
    client.post(f"/admin/clubs/{club_id}", data={"csrf_token": csrf(client), "name": "JS Premenovaná", "active": "on"})
    assert "JS Premenovaná" in client.get("/admin/clubs").text


def test_access_and_settings_only_for_system_admin(client, google, migrated_db):
    from ess.models import AdminRole
    from ess.services import admin_access

    with migrated_db() as s:
        admin_access.grant_access(s, SYSTEM, "office@example.org", "Kancelária", AdminRole.ADMIN)
        s.commit()
    login(client, google, email="office@example.org")
    assert client.get("/admin/access").status_code == 403
    page = client.get("/admin/settings").text  # administrators change the fee settings only (R44)
    assert 'id="settings-edit"' in page and "<fieldset disabled" in page and "ecp_qr_daily_limit" not in page
    assert "Ročná známka eCP" not in page and 'href="/admin/sticker"' in page  # sticker is under Členské (R45)
    client.post("/admin/settings", data={"csrf_token": csrf(client), "fee_amount": "99", "ecp_qr_daily_limit": "99"})
    page = client.get("/admin/settings").text
    assert 'value="99"' in page
    with migrated_db() as s:
        from ess.services import settings as settings_service

        assert settings_service.get_setting(s, "ecp_qr_daily_limit") == "10"  # superadmin only: ignored
    assert client.get("/admin/import").status_code == 403

    login(client, google)  # super admin
    token = csrf(client)
    client.post("/admin/access", data={"csrf_token": token, "email": "druhy@example.org", "name": "Druhý", "role": "admin"})
    page = client.get("/admin/access").text
    assert "druhy@example.org" in page and "Kancelária" in page
    client.post("/admin/settings", data={"csrf_token": token, "fee_amount": "16.00", "reduced_fee_amount": "7.00",
                                         "reduced_fee_age": "62", "fee_currency": "EUR"})
    page = client.get("/admin/settings").text
    assert 'value="16.00"' in page and 'id="settings-edit"' in page


def test_documents_page(client, google):
    login(client, google)
    token = csrf(client)
    client.post("/admin/documents", data={"csrf_token": token, "title": "Stanovy", "url": "https://example.org/s.pdf"})
    client.post("/admin/documents", data={"csrf_token": token, "title": "Zlý", "url": "ftp://x"}, follow_redirects=False)
    page = client.get("/admin/documents").text
    assert "Stanovy" in page and "Odkaz musí začínať https://" in page


def test_member_page_shows_shared_email(client, google, migrated_db):
    club_id = _club(migrated_db)
    login(client, google)
    ids = []
    for first in ("Ján", "Jana"):
        r = client.post("/admin/members/new", data={"csrf_token": csrf(client), "first_name": first,
                                                   "last_name": "Rodinný", "email": "rodina@example.org",
                                                   "club_id": str(club_id)}, follow_redirects=False)
        assert r.status_code == 303
        ids.append(_member_id_from(r))
    page = client.get(f"/admin/members/{ids[0]}").text
    assert "E-mail zdieľa aj" in page and "Jana Rodinný" in page
