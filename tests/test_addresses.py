"""Member address in parts, club contact details, migration of the former one-line address."""

import uuid
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from ess.models import Club, Member
from ess.security import pii
from ess.services import clubs, importing, members
from ess.services.access import SYSTEM, DomainError
from ess.services.members import MemberData
from tests.test_admin_forms import _club, _member_id_from
from tests.test_web_admin import client, csrf, google, login  # noqa: F401  (fixtures and helpers)


def test_full_address():
    data = MemberData(first_name="A", last_name="B", street="Hlavná 1", postal_code="031 01", city="Liptovský Mikuláš")
    assert data.full_address() == "Hlavná 1, 031 01 Liptovský Mikuláš"
    data.country = "CZ"
    assert data.full_address().endswith(", CZ")
    assert MemberData(first_name="A", last_name="B").full_address() == ""


def test_import_templates_contain_all_columns():
    for kind, columns in (("clubs", importing.CLUB_COLUMNS), ("members", importing.MEMBER_COLUMNS)):
        assert importing.template_csv(kind).lstrip("﻿").splitlines()[0].split(";") == columns


@pytest.mark.db
def test_member_address_parts_roundtrip(session):
    m = members.create_member(session, SYSTEM, MemberData(
        first_name="Eva", last_name="Adresná", street="Hlavná 1", postal_code="031 01", city="Mikuláš", country="cz"))
    data = members.read_member(m)
    assert (data.street, data.postal_code, data.city, data.country) == ("Hlavná 1", "031 01", "Mikuláš", "CZ")
    assert b"Hlavn" not in (m.street_enc or b"")  # encrypted
    with pytest.raises(DomainError):
        members.create_member(session, SYSTEM, MemberData(first_name="X", last_name="Y", country="Slovensko"))


@pytest.mark.db
def test_member_form_address(client, google, migrated_db):
    login(client, google)
    form = {"csrf_token": csrf(client), "first_name": "Ján", "last_name": "Adresný", "street": "Hlavná 1",
            "postal_code": "031 01", "city": "Liptovský Mikuláš", "country": "sk",
            "club_id": str(_club(migrated_db)), "status": "member"}
    member_id = _member_id_from(client.post("/admin/members/new", data=form, follow_redirects=False))
    assert "Hlavná 1, 031 01 Liptovský Mikuláš" in client.get(f"/admin/members/{member_id}").text


@pytest.mark.db
def test_club_contact_form_and_validation(client, google, migrated_db):
    login(client, google)
    club_id = _club(migrated_db)
    base = {"csrf_token": csrf(client), "name": "JS Formulárová", "active": "on", "street": "Jaskynná 5",
            "postal_code": "976 01", "city": "Brezno", "country": "SK", "email": "js@example.org",
            "phone": "+421 48 000 000", "web": "https://js.example.org", "founded_on": "1990-05-01"}
    client.post(f"/admin/clubs/{club_id}", data=base)
    with migrated_db() as s:
        club = s.get(Club, club_id)
        assert (club.city, club.email, club.founded_on) == ("Brezno", "js@example.org", date(1990, 5, 1))
    page = client.post(f"/admin/clubs/{club_id}", data={**base, "csrf_token": csrf(client), "web": "js.example.org"}).text
    assert "Web musí začínať" in page
    with migrated_db() as s:
        assert s.get(Club, club_id).web == "https://js.example.org"


@pytest.mark.db
def test_club_import_with_contacts(session):
    csv = ("kod;nazov;ulica;psc;obec;krajina;email;telefon;web;zalozena\n"
           "JS-A;JS A;Hlavná 1;031 01;Mikuláš;;a@example.org;+421 1;https://a.example.org;1990\n")
    assert importing.import_clubs(session, SYSTEM, csv.encode(), dry_run=False).ok
    club = session.scalar(select(Club).where(Club.code == "JS-A"))
    assert (club.city, club.country, club.founded_on, club.web) == ("Mikuláš", "SK", date(1990, 1, 1),
                                                                   "https://a.example.org")
    bad = "kod;nazov;email;web;krajina;zalozena\nJS-B;JS B;x;www.b.sk;Slovensko;zajtra\n"
    result = importing.import_clubs(session, SYSTEM, bad.encode(), dry_run=True)
    assert not result.ok and len(result.errors) == 4


@pytest.mark.db
def test_member_import_address_columns_and_legacy_header(session):
    importing.import_clubs(session, SYSTEM, b"kod;nazov\nJS-A;JS A\n", dry_run=False)
    csv = ("kod_skupiny;primarna;stav;meno;priezvisko;bydlisko;psc;mesto\n"
           "JS-A;X;člen;Ján;Importný;Hlavná 1;031 01;Mikuláš\n")
    assert importing.import_members(session, SYSTEM, csv.encode(), dry_run=False).ok
    member = session.scalar(select(Member))
    data = members.read_member(member)
    assert (data.street, data.postal_code, data.city, data.country) == ("Hlavná 1", "031 01", "Mikuláš", "SK")


@pytest.mark.db
def test_migration_keeps_former_address(migrated_db):
    from ess.db import get_engine

    config = Config("alembic.ini")
    command.downgrade(config, "0008")
    member_id = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(text("INSERT INTO members (id, first_name_enc, last_name_enc, address_enc, reduced_fee, "
                          "created_at, updated_at) VALUES (:id, :f, :l, :a, false, now(), now())"),
                     {"id": member_id, "f": pii.encrypt("Ján", "members.first_name"),
                      "l": pii.encrypt("Starý", "members.last_name"),
                      "a": pii.encrypt("Hlavná 1, Mikuláš", "members.address")})
    command.upgrade(config, "head")
    with migrated_db() as s:
        data = members.read_member(s.get(Member, member_id))
    assert data.street == "Hlavná 1, Mikuláš" and data.country == "SK"
