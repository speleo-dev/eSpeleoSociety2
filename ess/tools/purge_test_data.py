"""Delete all members, clubs (except "SSS – nezaradení") and everything tied to them – test data only.

Before importing real data into a database that was used for testing. Kept: administrators, settings,
documents, positions catalogue, certificate types and the audit log (it holds no personal data).
Refuses to run with ESS_ENVIRONMENT=prod and without --yes.

    ESS_DATABASE_URL=... ESS_MEDIA_BUCKET=... .venv/bin/python -m ess.tools.purge_test_data --yes
    .venv/bin/python -m ess.tools.load_clubs    # the SSS clubs again
"""

import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

# Children first (foreign keys).
TABLES = [
    "member_passkeys", "member_sessions", "member_login_codes", "cave_trips",
    "ecp_notification_deliveries", "ecp_notifications", "verification_tokens", "one_time_tokens",
    "tasks", "bank_transactions", "bank_statements", "payment_reference_items", "fees", "payment_references",
    "consents", "ecp_passes", "ecp_applications", "sss_cards", "club_delegations", "position_holders",
    "member_certificates", "memberships", "members",
]


def purge(session: Session, store=None) -> dict[str, int]:
    photos = [row[0] for row in session.execute(text(
        "SELECT photo FROM ecp_passes WHERE photo IS NOT NULL UNION "
        "SELECT photo_original FROM ecp_applications WHERE photo_original IS NOT NULL UNION "
        "SELECT photo_cropped FROM ecp_applications WHERE photo_cropped IS NOT NULL"))]
    counts = {}
    for table in TABLES:
        counts[table] = session.execute(text(f"DELETE FROM {table}")).rowcount  # noqa: S608 (fixed names)
    counts["clubs"] = session.execute(text("DELETE FROM clubs WHERE NOT is_unaffiliated")).rowcount
    session.commit()
    if store is not None:
        for name in photos:
            try:
                store.delete(name)
            except Exception:  # a missing object is fine
                pass
    counts["photos"] = len(photos)
    return counts


def main() -> None:
    from ess.config import get_settings
    from ess.db import get_sessionmaker
    from ess.storage import get_media_store

    if get_settings().environment == "prod":
        sys.exit("Refusing to delete data in production (ESS_ENVIRONMENT=prod).")
    if "--yes" not in sys.argv:
        sys.exit("This deletes ALL members and clubs. Run again with --yes to confirm.")
    with get_sessionmaker()() as session:
        counts = purge(session, get_media_store())
    print(", ".join(f"{table}: {n}" for table, n in counts.items() if n))


if __name__ == "__main__":
    main()
