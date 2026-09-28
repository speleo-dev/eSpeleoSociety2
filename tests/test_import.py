"""CSV import of clubs and members."""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from ess.models import Club, Member, Membership, MembershipStatus
from ess.services import importing, members
from ess.services.access import Actor
from ess.services.members import MemberData

ADMIN = Actor(kind="admin", id="admin-1")

CLUBS = "kod;nazov;skratka;cakatelia\nJS-DEM;Jaskyniarska skupina Demänová;JS Demänová;X\nos-lip;Oblastná skupina Liptov;;\n"
MEMBERS = (
    "Kód skupiny;Primárna;Stav;Titul pred;Meno;Priezvisko;Titul za;Dátum narodenia;E-mail;Telefón;Bydlisko;"
    "Číslo preukazu;Člen SSS od;Zľava\n"
    "JS-DEM;X;člen;Ing.;Ján;Vzorový;;15.3.1975;rodina@example.org;;;1234;1995;\n"
    "OS-LIP;;člen;;Ján;Vzorový;;;;;;;;\n"
    "JS-DEM;x;čakateľ;;Eva;Vzorová;;2. 8. 2001;rodina@example.org;;;;;X\n"
)


def enc(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


def test_read_csv_detects_delimiter_encoding_and_headers():
    headers, rows = importing.read_csv(enc("﻿Kód skupiny,Meno\nA,Ján\n"))
    assert headers == ["kod_skupiny", "meno"] and rows == [{"kod_skupiny": "A", "meno": "Ján"}]
    headers, rows = importing.read_csv(enc("kod;nazov\nA;Žilina\n", "cp1250"))
    assert rows[0]["nazov"] == "Žilina"
    headers, _ = importing.read_csv(enc("E-mail;Tel. číslo;Primárny;Skupina\n"))
    assert headers == ["email", "telefon", "primarna", "kod_skupiny"]


@pytest.mark.parametrize("value,expected", [
    ("31.12.1980", date(1980, 12, 31)), ("1. 2. 1990", date(1990, 2, 1)), ("1980-12-31", date(1980, 12, 31)),
    ("1995", date(1995, 1, 1)), ("", None),
])
def test_parse_date_flexible(value, expected):
    assert importing.parse_date_flexible(value) == expected



@pytest.mark.db
def test_import_clubs_then_members(session):
    check = importing.import_clubs(session, ADMIN, enc(CLUBS), dry_run=True)
    assert check.ok and session.scalar(select(func.count()).select_from(Club)) == 1  # only "SSS - nezaradení"
    result = importing.import_clubs(session, ADMIN, enc(CLUBS), dry_run=False)
    assert result.ok and result.created == 2
    lip = session.scalars(select(Club).where(Club.code == "OS-LIP")).one()
    assert lip.uses_candidates is False  # empty "cakatelia"
    again = importing.import_clubs(session, ADMIN, enc(CLUBS), dry_run=True)
    assert not again.ok and "kód JS-DEM už existuje" in again.errors[0]

    result = importing.import_members(session, ADMIN, enc(MEMBERS), dry_run=False)
    assert result.ok, result.errors
    assert session.scalar(select(func.count()).select_from(Member)) == 2
    jan = members.find_by_lookup(session, "Ján", "Vzorový", 1975)[0]
    data = members.read_member(jan)
    assert (data.title_before, data.card_number, data.member_since) == ("Ing.", "1234", date(1995, 1, 1))
    clubs_of_jan = session.execute(
        select(Club.code, Membership.is_primary).join(Membership, Membership.club_id == Club.id)
        .where(Membership.member_id == jan.id)
    ).all()
    assert sorted(clubs_of_jan) == [("JS-DEM", True), ("OS-LIP", False)]
    eva = members.find_by_lookup(session, "Eva", "Vzorová", 2001)[0]
    assert eva.reduced_fee and members.members_sharing_email(session, eva) == [jan]
    status = session.scalar(select(Membership.status).where(Membership.member_id == eva.id))
    assert status == MembershipStatus.CANDIDATE


@pytest.mark.db
def test_import_members_reports_errors_and_saves_nothing(session):
    importing.import_clubs(session, ADMIN, enc(CLUBS), dry_run=False)
    members.create_member(session, ADMIN, MemberData("Existujúci", "Člen", card_number="999"))
    bad = (
        "kod_skupiny;primarna;stav;meno;priezvisko;datum_narodenia;cislo_preukazu\n"
        "XXX;X;člen;Ján;Neznámy;;\n"                      # 2: unknown club
        "JS-DEM;X;iný;Peter;Zlý;32.13.1980;\n"              # 3: bad status and date
        "OS-LIP;X;čakateľ;Pavol;Čakateľ;;\n"                # 4: club without candidates
        "JS-DEM;X;člen;Anna;Duplicitná;;999\n"             # 5: card number in DB
        "OS-LIP;;člen;Nikto;Neexistuje;;\n"                # 6: secondary row without primary
        "JS-DEM;X;člen;Mária;Dvojitá;1.1.1980;\n"          # 7
        "JS-DEM;X;člen;Mária;Dvojitá;1.1.1980;\n"          # 8: same person twice as primary
    )
    result = importing.import_members(session, ADMIN, enc(bad), dry_run=False)
    assert not result.ok
    text = "\n".join(result.errors)
    for expected in ("Riadok 2: neznámy kód skupiny", "Riadok 3: stav musí byť", "Riadok 3: neplatný dátum",
                     "Riadok 4: skupina OS-LIP nepoužíva čakateľov", "Riadok 5: číslo preukazu už má člen",
                     "Riadok 6: neprimárne členstvo", "Riadok 8: rovnaký človek ako v riadku 7"):
        assert expected in text
    assert "Ján" not in text and "Anna" not in text  # no personal data in messages
    assert session.scalar(select(func.count()).select_from(Member)) == 1


@pytest.mark.db
def test_ambiguous_secondary_row_needs_birth_date(session):
    importing.import_clubs(session, ADMIN, enc(CLUBS), dry_run=False)
    csv_text = (
        "kod_skupiny;primarna;meno;priezvisko;datum_narodenia\n"
        "JS-DEM;X;Peter;Novák;1.1.1970\n"
        "JS-DEM;X;Peter;Novák;2.2.1990\n"
        "OS-LIP;;Peter;Novák;\n"
    )
    result = importing.import_members(session, ADMIN, enc(csv_text), dry_run=True)
    assert not result.ok and "nájdených 2" in result.errors[0]
    fixed = csv_text.replace("OS-LIP;;Peter;Novák;\n", "OS-LIP;;Peter;Novák;2.2.1990\n")
    assert importing.import_members(session, ADMIN, enc(fixed), dry_run=True).ok


@pytest.mark.db
def test_import_page_upload(migrated_db, monkeypatch):
    from tests.test_web_admin import FakeGoogle, csrf, login
    from ess.config import get_settings
    from ess.main import create_app
    from ess.web import auth

    monkeypatch.setenv("ESS_GOOGLE_CLIENT_ID", "1-x.apps.googleusercontent.com")
    monkeypatch.setenv("ESS_GOOGLE_CLIENT_SECRET", "s")
    get_settings.cache_clear()
    google = FakeGoogle()
    monkeypatch.setattr(auth, "_google", lambda: google)
    client = TestClient(create_app())
    login(client, google)
    files = {"file": ("skupiny.csv", enc(CLUBS), "text/csv")}
    check = client.post("/admin/import/clubs", data={"csrf_token": csrf(client)}, files=files)
    assert check.status_code == 200 and "kontrola bez chýb" in check.text
    done = client.post("/admin/import/clubs", data={"csrf_token": csrf(client), "execute": "on"}, files=files)
    assert "Naimportovaných 2 skupín." in done.text
    codes = client.get("/admin/import/club-codes.csv")
    assert "JS-DEM;Jaskyniarska skupina Demänová" in codes.text
    template = client.get("/admin/import/template/members.csv")
    assert template.headers["content-type"].startswith("text/csv") and "kod_skupiny" in template.text
