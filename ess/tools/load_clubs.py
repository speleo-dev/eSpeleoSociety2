"""Load the SSS clubs and their logos (ess/data/clubs) into the database – initial setup and development.

Safe to run again: an existing club (same code or name) is kept; a missing logo is added.
Club names and logos are public, not personal data.

    ESS_DATABASE_URL=... ESS_MEDIA_BUCKET=... .venv/bin/python -m ess.tools.load_clubs
"""

import csv
import io
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ess.models import Club
from ess.security.crypto import normalize_for_index
from ess.services import clubs
from ess.services.access import SYSTEM

DATA = Path(__file__).resolve().parent.parent / "data" / "clubs"


@dataclass
class LoadResult:
    created: int = 0
    existing: int = 0
    logos: int = 0


def rows(data_dir: Path = DATA) -> list[dict[str, str]]:
    text = (data_dir / "clubs.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def load(session: Session, store, data_dir: Path = DATA) -> LoadResult:
    """Create missing clubs; upload a logo where the club has none (needs a media store)."""
    by_code = {c.code: c for c in session.scalars(select(Club)) if c.code}
    by_name = {normalize_for_index(c.name): c for c in session.scalars(select(Club))}
    result = LoadResult()
    for row in rows(data_dir):
        club = by_code.get(row["kod"]) or by_name.get(normalize_for_index(row["nazov"]))
        if club is None:
            club = clubs.create_club(session, SYSTEM, row["nazov"], "", True, code=row["kod"])
            result.created += 1
        else:
            result.existing += 1
        if row.get("logo_subor") and not club.logo_url and store is not None:
            clubs.set_logo(session, SYSTEM, club.id, (data_dir / "logos" / row["logo_subor"]).read_bytes(), store)
            result.logos += 1
    return result


def main() -> None:
    from ess.db import get_sessionmaker
    from ess.storage import get_media_store

    store = get_media_store()
    if store is None:
        print("ESS_MEDIA_BUCKET is not set - clubs are loaded without logos.", file=sys.stderr)
    with get_sessionmaker()() as session:
        result = load(session, store)
        session.commit()
    print(f"Clubs created: {result.created}, already present: {result.existing}, logos uploaded: {result.logos}")


if __name__ == "__main__":
    main()
