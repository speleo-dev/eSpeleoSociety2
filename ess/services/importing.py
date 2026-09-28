"""CSV import of clubs and members (initial data load). See docs/import.md.

Both imports are all-or-nothing: the file is checked first and nothing is saved if any row has an error.
Error messages name the row and column, never the personal data itself.
"""

import csv
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess.models import Club, Member, MembershipStatus
from ess.security.crypto import normalize_for_index
from ess.services import clubs as clubs_service
from ess.services import members as members_service
from ess.services import memberships
from ess.services.access import Actor, DomainError, require_admin
from ess.services.members import MemberData

CLUB_COLUMNS = ["kod", "nazov", "skratka", "cakatelia", "logo"]
MEMBER_COLUMNS = ["kod_skupiny", "primarna", "stav", "titul_pred", "meno", "priezvisko", "titul_za",
                  "datum_narodenia", "email", "telefon", "bydlisko", "cislo_preukazu", "clen_sss_od", "zlava"]
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,19}$")
_TRUE = {"x", "1", "ano", "true", "t", "yes", "y"}


@dataclass
class ImportResult:
    ok: bool
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    created: int = 0
    summary: str = ""


# Common alternative header names people use in spreadsheets.
_ALIASES = {"e_mail": "email", "mail": "email", "tel": "telefon", "telefonne_cislo": "telefon",
            "tel_cislo": "telefon", "adresa": "bydlisko", "skupina": "kod_skupiny", "kod_klubu": "kod_skupiny",
            "cislo_papieroveho_preukazu": "cislo_preukazu", "narodeny": "datum_narodenia", "zlavnene": "zlava",
            "zlavnene_clenske": "zlava", "nazov_skupiny": "nazov", "primarny": "primarna"}


def _key(header: str) -> str:
    """Header normalisation: case, diacritics and spaces do not matter ("Kód skupiny" == "kod_skupiny")."""
    text = unicodedata.normalize("NFKD", header.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[\s.\-]+", "_", text).strip("_")
    return _ALIASES.get(text, text)


def read_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Decode (UTF-8 with or without BOM, fallback Windows-1250), detect ';' or ',' and return rows."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1250")
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    lines = [row for row in reader if any(cell.strip() for cell in row)]
    if not lines:
        return [], []
    headers = [_key(h) for h in lines[0]]
    rows = [{headers[i]: (row[i].strip() if i < len(row) else "") for i in range(len(headers))} for row in lines[1:]]
    return headers, rows


def _flag(value: str) -> bool:
    return _key(value) in _TRUE


def parse_date_flexible(value: str) -> date | None:
    """Accepts 31.12.1980, 31. 12. 1980, 1980-12-31 or just a year (1980 -> 1.1.1980)."""
    value = value.strip()
    if not value:
        return None
    if re.fullmatch(r"\d{4}", value):
        return date(int(value), 1, 1)
    m = re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", value)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return date.fromisoformat(value)


def _missing_columns(headers: list[str], required: list[str]) -> list[str]:
    return [c for c in required if c not in headers]


# --- clubs ---------------------------------------------------------------------------------------------

def import_clubs(session: Session, actor: Actor, content: bytes, dry_run: bool = True) -> ImportResult:
    require_admin(actor)
    headers, rows = read_csv(content)
    missing = _missing_columns(headers, ["kod", "nazov"])
    if missing:
        return ImportResult(False, errors=[f"Chýbajú stĺpce: {', '.join(missing)}"])
    existing_codes = {c for c in session.scalars(select(Club.code)) if c}
    existing_names = {normalize_for_index(n) for n in session.scalars(select(Club.name))}
    errors: list[str] = []
    seen_codes: set[str] = set()
    seen_names: set[str] = set()
    for i, row in enumerate(rows, start=2):
        code = row.get("kod", "").strip().upper()
        name = " ".join(row.get("nazov", "").split())
        if not CODE_RE.match(code):
            errors.append(f"Riadok {i}: neplatný kód (povolené A–Z, 0–9, - a _, najviac 20 znakov).")
        elif code in existing_codes or code in seen_codes:
            errors.append(f"Riadok {i}: kód {code} už existuje.")
        if not name:
            errors.append(f"Riadok {i}: chýba názov.")
        logo = row.get("logo", "").strip()
        if logo and not logo.startswith("https://"):
            errors.append(f"Riadok {i}: adresa loga musí začínať https://")
        elif normalize_for_index(name) in existing_names or normalize_for_index(name) in seen_names:
            errors.append(f"Riadok {i}: skupina s rovnakým názvom už existuje.")
        seen_codes.add(code)
        seen_names.add(normalize_for_index(name))
    result = ImportResult(not errors, rows=len(rows), errors=errors)
    if errors or dry_run:
        result.summary = f"{len(rows)} skupín" + (" – bez chýb, pripravené na import." if not errors else "")
        return result
    for row in rows:
        # Column "cakatelia": X = the club uses candidates, empty = it does not. Missing column = uses them.
        uses_candidates = _flag(row["cakatelia"]) if "cakatelia" in headers else True
        clubs_service.create_club(session, actor, row["nazov"], row.get("skratka", ""), uses_candidates,
                                  code=row["kod"], logo_url=row.get("logo", ""))
    result.created = len(rows)
    result.summary = f"Naimportovaných {len(rows)} skupín."
    return result


# --- members -------------------------------------------------------------------------------------------

@dataclass
class _MemberRow:
    line: int
    club_code: str
    primary: bool
    status: MembershipStatus
    data: MemberData | None  # only for primary rows
    first_name: str
    last_name: str
    birth_date: date | None
    card_number: str | None


def _identity(first: str, last: str) -> str:
    return normalize_for_index(f"{first} {last}")


def import_members(session: Session, actor: Actor, content: bytes, dry_run: bool = True) -> ImportResult:
    """Import members; one row per membership. Personal data come from the primary row."""
    require_admin(actor)
    headers, rows = read_csv(content)
    missing = _missing_columns(headers, ["kod_skupiny", "primarna", "meno", "priezvisko"])
    if missing:
        return ImportResult(False, errors=[f"Chýbajú stĺpce: {', '.join(missing)}"])
    clubs = {c.code: c for c in session.scalars(select(Club)) if c.code}
    errors: list[str] = []
    parsed: list[_MemberRow] = []

    for i, row in enumerate(rows, start=2):
        def err(msg: str) -> None:
            errors.append(f"Riadok {i}: {msg}")

        code = row.get("kod_skupiny", "").strip().upper()
        club = clubs.get(code)
        if club is None:
            err(f"neznámy kód skupiny „{code}“.")
        elif not club.active:
            err(f"skupina {code} nie je aktívna.")
        status_text = _key(row.get("stav", "") or "clen")
        if status_text in ("clen", "member"):
            status = MembershipStatus.MEMBER
        elif status_text in ("cakatel", "candidate"):
            status = MembershipStatus.CANDIDATE
            if club is not None and not club.uses_candidates:
                err(f"skupina {code} nepoužíva čakateľov.")
        else:
            err("stav musí byť „člen“ alebo „čakateľ“.")
            status = MembershipStatus.MEMBER
        first, last = row.get("meno", "").strip(), row.get("priezvisko", "").strip()
        if not first or not last:
            err("chýba meno alebo priezvisko.")
        dates = {}
        for col in ("datum_narodenia", "clen_sss_od"):
            try:
                dates[col] = parse_date_flexible(row.get(col, ""))
            except ValueError:
                err(f"neplatný dátum v stĺpci {col} (použite 31.12.1980 alebo 1980-12-31).")
                dates[col] = None
        email = row.get("email", "").strip() or None
        if email and "@" not in email:
            err("neplatný e-mail.")
        primary = _flag(row.get("primarna", ""))
        data = None
        if primary:
            data = MemberData(
                first_name=first, last_name=last,
                title_before=row.get("titul_pred", "").strip() or None,
                title_after=row.get("titul_za", "").strip() or None,
                birth_date=dates["datum_narodenia"], email=email,
                phone=row.get("telefon", "").strip() or None,
                address=row.get("bydlisko", "").strip() or None,
                card_number=row.get("cislo_preukazu", "").strip() or None,
                member_since=dates["clen_sss_od"],
                reduced_fee=_flag(row.get("zlava", "")),
            )
        parsed.append(_MemberRow(i, code, primary, status, data, first, last, dates["datum_narodenia"],
                                 row.get("cislo_preukazu", "").strip() or None))

    # Link secondary rows to exactly one primary row of the same person.
    primaries = [p for p in parsed if p.primary]
    links: dict[int, _MemberRow] = {}
    for p in parsed:
        if p.primary:
            continue
        candidates = [q for q in primaries if _identity(q.first_name, q.last_name) == _identity(p.first_name, p.last_name)
                      and (p.birth_date is None or q.birth_date == p.birth_date)
                      and (p.card_number is None or q.card_number == p.card_number)]
        if len(candidates) != 1:
            errors.append(f"Riadok {p.line}: neprimárne členstvo sa nedá jednoznačne priradiť k riadku s primárnou "
                          f"skupinou (nájdených {len(candidates)}); doplňte dátum narodenia alebo číslo preukazu.")
        else:
            links[p.line] = candidates[0]
            if candidates[0].club_code == p.club_code:
                errors.append(f"Riadok {p.line}: rovnaká skupina ako v primárnom riadku {candidates[0].line}.")

    # Duplicates inside the file and against the database.
    seen: dict[tuple, int] = {}
    card_numbers: dict[str, int] = {}
    for p in primaries:
        key = (_identity(p.first_name, p.last_name), p.birth_date)
        if key in seen:
            errors.append(f"Riadok {p.line}: rovnaký človek ako v riadku {seen[key]} (obaja označení ako primárni).")
        seen[key] = p.line
        if p.card_number:
            if p.card_number in card_numbers:
                errors.append(f"Riadok {p.line}: číslo preukazu je rovnaké ako v riadku {card_numbers[p.card_number]}.")
            card_numbers[p.card_number] = p.line
            if members_service.find_by_card_number(session, p.card_number):
                errors.append(f"Riadok {p.line}: číslo preukazu už má člen v databáze.")
        if p.birth_date and members_service.find_by_lookup(session, p.first_name, p.last_name, p.birth_date.year):
            errors.append(f"Riadok {p.line}: člen s rovnakým menom a rokom narodenia už je v databáze.")

    result = ImportResult(not errors, rows=len(rows), errors=errors)
    summary = f"{len(primaries)} členov, {len(parsed) - len(primaries)} ďalších členstiev"
    if errors or dry_run:
        result.summary = summary + (" – bez chýb, pripravené na import." if not errors else "")
        return result

    created: dict[int, uuid.UUID] = {}
    for p in primaries:
        membership = memberships.add_new_member_to_club(session, actor, p.data, clubs[p.club_code].id, p.status)
        created[p.line] = membership.member_id
    for p in parsed:
        if not p.primary:
            member_id = created[links[p.line].line]
            memberships.add_membership(session, actor, member_id, clubs[p.club_code].id, p.status)
    result.created = len(primaries)
    result.summary = f"Naimportovaných {summary}."
    return result


def template_csv(kind: str) -> str:
    """Header and fictional example rows for the person preparing the data (';' for Slovak Excel)."""
    if kind == "clubs":
        rows = [CLUB_COLUMNS, ["JS-DEM", "Jaskyniarska skupina Demänová", "JS Demänová", "X",
                               "https://storage.googleapis.com/BUCKET/club_logos/js-dem.png"],
                ["OS-LIP", "Oblastná skupina Liptov", "OS Liptov", "", ""]]
    else:
        rows = [MEMBER_COLUMNS,
                ["JS-DEM", "X", "člen", "Ing.", "Ján", "Vzorový", "", "15.3.1975", "jan.vzorovy@example.org",
                 "+421 900 000 000", "Hlavná 1, Liptovský Mikuláš", "1234", "1995", ""],
                ["OS-LIP", "", "člen", "", "Ján", "Vzorový", "", "", "", "", "", "", "", ""],
                ["JS-DEM", "X", "čakateľ", "", "Eva", "Ukážková", "", "2.8.2001", "eva@example.org", "", "", "", "", ""]]
    out = io.StringIO()
    csv.writer(out, delimiter=";", lineterminator="\r\n").writerows(rows)
    return "﻿" + out.getvalue()  # BOM so that Excel opens UTF-8 correctly
