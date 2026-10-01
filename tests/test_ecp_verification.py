"""Verification page behind the eCP QR code: single-use token, grace period, daily limit, outcomes."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from ess.models import EcpPass, VerificationToken
from ess.services import ecp_issuance, members, positions, settings
from ess.services import ecp_verification as ver
from ess.services.access import SYSTEM
from ess.services.ecp_verification import Outcome
from ess.storage import MemoryMediaStore
from ess.wallet import MemoryWalletClient, WalletError
from tests.test_ecp_issuance import ADMIN, _submitted

pytestmark = pytest.mark.db
BASE = "https://ess"


def _issued(session):
    store, wallet = MemoryMediaStore(), MemoryWalletClient()
    app, member_id = _submitted(session, store)
    ecp_issuance.approve(session, ADMIN, app.id, store, wallet, BASE)
    ecp_pass = session.scalar(select(EcpPass))
    return wallet, ecp_pass, member_id


def _qr_token(wallet, ecp_pass) -> str:
    return wallet.objects[ecp_pass.wallet_object_id]["barcode"]["value"].rsplit("/", 1)[1]


def test_first_scan_rotates_qr_and_grace_period(session):
    wallet, ecp_pass, _ = _issued(session)
    first = _qr_token(wallet, ecp_pass)
    result = ver.verify(session, first, wallet, BASE)
    assert result.outcome == Outcome.VALID and result.full_name == "Ján Žiadateľ" and result.club_name
    second = _qr_token(wallet, ecp_pass)
    assert second != first  # the pass shows a new QR
    assert ver.verify(session, first, wallet, BASE).outcome == Outcome.VALID  # within grace period
    row = session.scalar(select(VerificationToken).where(VerificationToken.token_hash == ecp_issuance.hash_token(first)))
    row.first_used_at = datetime.now(UTC) - timedelta(minutes=16)
    session.flush()
    assert ver.verify(session, first, wallet, BASE).outcome == Outcome.USED
    assert ver.verify(session, second, wallet, BASE).outcome == Outcome.VALID
    assert ver.verify(session, "unknown-token", wallet, BASE).outcome == Outcome.UNKNOWN


def test_daily_limit_and_wallet_error_keep_the_token(session):
    wallet, ecp_pass, _ = _issued(session)
    settings.set_setting(session, SYSTEM, "ecp_qr_daily_limit", "1")  # the issuing token already counts
    token = _qr_token(wallet, ecp_pass)
    assert ver.verify(session, token, wallet, BASE).outcome == Outcome.VALID
    assert _qr_token(wallet, ecp_pass) == token
    row = session.scalar(select(VerificationToken))
    assert row.first_used_at is None  # not consumed, so the QR in the pass keeps working
    settings.set_setting(session, SYSTEM, "ecp_qr_daily_limit", "10")

    class Broken(MemoryWalletClient):
        def patch_object(self, object_id, fields):
            raise WalletError("patch: HTTP 500")

    broken = Broken()
    broken.objects = wallet.objects
    assert ver.verify(session, token, broken, BASE).outcome == Outcome.VALID
    assert session.scalar(select(func.count()).select_from(VerificationToken)) == 1  # new token rolled back


def test_revoked_suspended_and_expelled(session):
    wallet, ecp_pass, member_id = _issued(session)
    token = _qr_token(wallet, ecp_pass)
    ecp_pass.state = "inactive"
    session.flush()
    assert ver.verify(session, token, wallet, BASE).outcome == Outcome.SUSPENDED
    assert _qr_token(wallet, ecp_pass) == token  # no rotation for an inactive pass
    ecp_pass.state = "active"
    members.expel_member(session, SYSTEM, member_id, "test")
    result = ver.verify(session, token, wallet, BASE)
    assert result.outcome == Outcome.NOT_MEMBER and result.full_name == ""  # no personal data
    ecp_pass.state = "revoked"
    session.flush()
    assert ver.verify(session, token, wallet, BASE).outcome == Outcome.NOT_MEMBER


def test_contacts_of_club_chair_and_sss_chair(session):
    wallet, ecp_pass, member_id = _issued(session)
    club_id = ver._primary_club(session, member_id).id
    positions.assign_position(session, SYSTEM, "club_chair", member_id, club_id=club_id)
    positions.assign_position(session, SYSTEM, "sss_chair", member_id)
    result = ver.verify(session, _qr_token(wallet, ecp_pass), wallet, BASE)
    assert [c.role for c in result.contacts] == ["Predseda skupiny", "Predseda SSS"]


def test_web_page_headers_and_content(migrated_db):
    from fastapi.testclient import TestClient

    from ess.main import create_app
    from ess.storage import get_media_store
    from ess.wallet import get_wallet

    from ess.models import Club, Membership
    from ess.services import payments
    from ess.services.access import SYSTEM
    from datetime import date as _date

    with migrated_db() as s:
        wallet, ecp_pass, member_id = _issued(s)
        club = s.get(Club, s.query(Membership.club_id).filter(Membership.member_id == member_id).scalar())
        club.logo_url = "https://storage.example/logos/js.png"
        payments.mark_paid(s, SYSTEM, member_id, _date.today().year, "hotovosť")
        token = _qr_token(wallet, ecp_pass)
        s.commit()
    app = create_app()
    app.dependency_overrides.update({get_wallet: lambda: wallet, get_media_store: lambda: MemoryMediaStore()})
    client = TestClient(app)
    response = client.get(f"/v/{token}")
    assert response.status_code == 200 and "Člen Slovenskej speleologickej spoločnosti" in response.text
    assert "Ján Žiadateľ" in response.text and re.search(r"Overené \d\d\.\d\d\.\d{4}", response.text)
    assert response.headers["cache-control"] == "no-store" and "noindex" in response.headers["x-robots-tag"]
    assert 'src="https://storage.example/logos/js.png" alt="Logo skupiny"' in response.text
    assert f"zaplatené do 31. 12. {_date.today().year}" in response.text
    bad = client.get("/v/nonsense")
    assert "Preukaz sa nepodarilo overiť" in bad.text and "Ján" not in bad.text
