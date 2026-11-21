"""Fixes from the security / UX audits of November 2026 (R57)."""

import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from ess.models import EcpPass, MemberSession
from ess.services import directory, members, outbox, portal_auth, positions
from ess.services.access import SYSTEM, Actor, DomainError
from tests.test_ecp_application import _club, _member
from tests.test_web_admin import client, csrf, google, login  # noqa: F401 (fixtures)

pytestmark = pytest.mark.db


# --- the club chair and the e-mail of a member -------------------------------------------------------


def _chair(session, club_id):
    chair = _member(session, club_id, first_name="Predseda", card_number="900", email="predseda@example.org")
    positions.assign_position(session, SYSTEM, "club_chair", chair, club_id)
    return Actor(kind="member", id=str(chair))


def _data(session, member_id, email):
    data = members.read_member(session.get(members.Member, member_id))
    data.email = email
    return data


def test_chair_cannot_change_email_of_member_with_ecp(session):
    club_id = _club(session)
    chair = _chair(session, club_id)
    plain = _member(session, club_id, first_name="Bez", card_number="901", email="stara@example.org")
    with_ecp = _member(session, club_id, first_name="Seecp", card_number="902", email="ecp@example.org")
    session.add(EcpPass(member_id=with_ecp, wallet_object_id="i.ecp", state="active"))
    session.flush()
    with pytest.raises(DomainError, match="email_change_admin_only"):
        members.update_member(session, chair, with_ecp, _data(session, with_ecp, "utocnik@example.org"))
    # a member of the chair's club without eCP: allowed (e.g. a typo before the eCP invitation)
    outbox.discard(session)
    members.update_member(session, chair, plain, _data(session, plain, "nova@example.org"))
    [mail] = outbox.take(session)
    assert mail.to == "stara@example.org" and mail.template == "email_changed"  # the old address is told
    # the administrator may change it always
    members.update_member(session, Actor(kind="admin", id="a"), with_ecp, _data(session, with_ecp, "nova2@example.org"))


def test_email_change_signs_out_portal_sessions(session):
    club_id = _club(session)
    member_id = _member(session, club_id, email="stara@example.org")
    session.add(EcpPass(member_id=member_id, wallet_object_id="i.x", state="active"))
    portal_auth.open_session(session, member_id, "email_code")
    session.flush()
    members.update_member(session, Actor(kind="admin", id="a"), member_id, _data(session, member_id, "nova@example.org"))
    rows = session.scalars(select(MemberSession).where(MemberSession.member_id == member_id)).all()
    assert rows and all(r.revoked_at is not None for r in rows)


def test_member_email_must_be_one_plain_address(session):
    club_id = _club(session)
    member_id = _member(session, club_id)
    for bad in ("a@b.sk, c@d.sk", "a@b.sk\nBcc: x@y.sk", "Ján <a@b.sk>"):
        with pytest.raises(DomainError, match="invalid_email"):
            members.update_member(session, SYSTEM, member_id, _data(session, member_id, bad))


# --- positions entered for a future date ----------------------------------------------------------------


def test_future_chair_is_not_shown_before_the_date(session):
    club_id = _club(session)
    old = _member(session, club_id, first_name="Starý", card_number="910")
    new = _member(session, club_id, first_name="Nový", card_number="911")
    positions.assign_position(session, SYSTEM, "club_chair", old, club_id, valid_from=date.today() - timedelta(days=30))
    positions.assign_position(session, SYSTEM, "club_chair", new, club_id, valid_from=date.today() + timedelta(days=10))
    session.flush()
    chair_ids = {h.member_id for h in directory.current_positions(session) if h.club_id == club_id}
    assert chair_ids == {old}


# --- web: payments "bez skupiny", CSV, headers, API docs ------------------------------------------------


def test_payments_without_club_and_csv_formulas(migrated_db, google, client):  # noqa: F811
    from ess.services import memberships

    with migrated_db() as s:
        club_id = _club(s)
        member_id = _member(s, club_id, last_name="=HYPERLINK(1)")
        from ess.services import payments

        payments.mark_paid(s, SYSTEM, member_id, date.today().year, "hotovosť")  # paid, then left the club
        for m in s.get(members.Member, member_id).memberships:
            memberships.terminate(s, SYSTEM, m.id)
        s.commit()
    login(client, google)
    year = date.today().year
    page = client.get(f"/admin/payments?year={year}").text
    assert "club=none" in page
    page = client.get(f"/admin/payments?year={year}&club=none").text
    assert "=HYPERLINK(1)" in page  # the member without a club is listed
    csv_text = client.get(f"/admin/payments/export.csv?year={year}&club=none").text
    assert "'=HYPERLINK(1)" in csv_text and ";=HYPERLINK" not in csv_text


def test_security_and_cache_headers(migrated_db, google, client):  # noqa: F811
    login(client, google)
    page = client.get("/admin/members")
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert 'href="#main"' in page.text and 'id="main"' in page.text  # skip link
    css = client.get("/static/vendor/tabler/css/tabler.min.css", headers={"Accept-Encoding": "gzip"})
    assert css.headers["content-encoding"] == "gzip" and "max-age" in css.headers["cache-control"]
    assert "content-encoding" not in page.headers  # pages are not compressed (BREACH)


def test_api_docs_never_list_the_administration(client):  # noqa: F811
    schema = client.get("/openapi.json")
    if schema.status_code == 200:  # local development only
        assert not [p for p in schema.json()["paths"] if p.startswith("/admin")]


def test_members_page_refreshes_new_member_button(migrated_db, google, client):  # noqa: F811
    with migrated_db() as s:
        club_id = _club(s)
        s.commit()
    login(client, google)
    page = client.post("/admin/members", data={"csrf_token": csrf(client), "club": str(club_id), "q": ""},
                       headers={"HX-Request": "true"})
    actions = re.search(r'id="members-actions".*?</div>\s*</div>', page.text, re.S).group(0)
    assert f"/admin/members/new?club={club_id}" in actions
    assert page.headers["HX-Push-Url"] == f"/admin/members?club={club_id}"
    listing = client.get("/admin/members").text
    assert 'hx-select-oob="#members-actions"' in listing and 'tabindex="-1" aria-disabled' not in listing


def test_index_has_no_button_inside_link(client):  # noqa: F811
    assert "<a href=\"/ecp/apply\"><button" not in client.get("/").text
