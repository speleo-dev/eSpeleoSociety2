"""Google Wallet: eCP pass objects and the "Add to Google Wallet" link.

The Cloud Run service account calls the API and signs the link through the IAM Credentials API,
so no key file exists (verified by spikes/wallet-probe). The design follows the original template
(docs/reference/wallet/wallet_object_template.json).
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Protocol

from ess.config import get_settings

log = logging.getLogger(__name__)

WALLET_API = "https://walletobjects.googleapis.com/walletobjects/v1"
GCS = "https://storage.googleapis.com"
SAVE_URL = "https://pay.google.com/gp/v/save/"


class WalletError(Exception):
    """The Wallet API refused or failed; the message contains no personal data."""


@dataclass
class PassContent:
    """What is shown on the eCP. Built on the server only, never logged."""

    object_id: str
    member_name: str
    club_name: str
    card_number: str | None
    member_since: date | None
    birth_date: date | None
    photo_url: str
    check_url: str
    valid_until: date | None = None  # end of the last paid year (phase 3)
    hero_url: str | None = None  # yearly sticker
    state: str = "ACTIVE"


def _text(value: str) -> dict:
    return {"defaultValue": {"language": "sk", "value": value}}


def _date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def static_url(name: str) -> str:
    return f"{GCS}/{get_settings().media_bucket}/static/{name}"


def build_pass_object(content: PassContent) -> dict:
    """Generic pass object with the module ids of the original design."""
    s = get_settings()
    modules = [
        {"id": "primary_club", "header": "Klub", "body": content.club_name},
        {"id": "member_from", "header": "Členom od", "body": _date(content.member_since)},
        {"id": "member_id", "header": "Identifikačné číslo", "body": content.card_number or "—"},
        {"id": "birth_date", "header": "Dátum narodenia", "body": _date(content.birth_date)},
    ]
    barcode = {"type": "QR_CODE", "value": content.check_url}
    if content.valid_until:
        modules.append({"id": "valid_until", "header": "Platný do", "body": _date(content.valid_until)})
        barcode["alternateText"] = f"Platnosť do {_date(content.valid_until)}"
    return {
        "id": content.object_id,
        "classId": s.wallet_class_id,
        "state": content.state,
        "logo": {"sourceUri": {"uri": static_url("Logo_sss.png")}},
        "cardTitle": _text("Slovenská speleologická spoločnosť"),
        "header": _text(content.member_name),
        "wideLogo": {"sourceUri": {"uri": static_url("SSS_logo_meno.png")}},
        "barcode": barcode,
        "imageModulesData": [{"id": "photo", "mainImage": {"sourceUri": {"uri": content.photo_url}}}],
        "textModulesData": modules,
        "linksModuleData": {"uris": [{"id": "homepage", "uri": "https://www.speleology.sk", "description": "Web SSS"}]},
        **({"heroImage": {"sourceUri": {"uri": content.hero_url}}} if content.hero_url else {}),
    }


class WalletClient(Protocol):
    def upsert_object(self, obj: dict) -> None: ...

    def set_state(self, object_id: str, state: str) -> None: ...

    def patch_object(self, object_id: str, fields: dict) -> None: ...

    def save_url(self, object_id: str) -> str: ...


class GoogleWalletClient:
    """Real client; credentials come from the runtime service account (no key file)."""

    def _session(self, scope: str):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession, Request

        try:
            credentials, _ = google.auth.default(scopes=[scope])
            credentials.refresh(Request())
        except Exception as exc:  # no credentials (local development) or metadata server unavailable
            log.warning("Google credentials unavailable: %s", type(exc).__name__)
            raise WalletError("credentials unavailable") from None
        return AuthorizedSession(credentials), getattr(credentials, "service_account_email", "")

    def _check(self, response, action: str) -> None:
        if not response.ok:
            log.warning("Google Wallet %s failed: HTTP %s", action, response.status_code)
            raise WalletError(f"{action}: HTTP {response.status_code}")

    def upsert_object(self, obj: dict) -> None:
        session, _ = self._session("https://www.googleapis.com/auth/wallet_object.issuer")
        try:
            response = session.post(f"{WALLET_API}/genericObject", json=obj, timeout=20)
            if response.status_code == 409:
                response = session.put(f"{WALLET_API}/genericObject/{obj['id']}", json=obj, timeout=20)
        except OSError:
            raise WalletError("upsert: connection failed") from None
        self._check(response, "upsert")

    def set_state(self, object_id: str, state: str) -> None:
        self.patch_object(object_id, {"state": state})

    def patch_object(self, object_id: str, fields: dict) -> None:
        session, _ = self._session("https://www.googleapis.com/auth/wallet_object.issuer")
        try:
            response = session.patch(f"{WALLET_API}/genericObject/{object_id}", json=fields, timeout=20)
        except OSError:
            raise WalletError("patch: connection failed") from None
        self._check(response, "patch")

    def save_url(self, object_id: str) -> str:
        session, email = self._session("https://www.googleapis.com/auth/cloud-platform")
        claims = {"iss": email, "aud": "google", "typ": "savetowallet", "iat": int(time.time()), "origins": [],
                  "payload": {"genericObjects": [{"id": object_id}]}}
        try:
            response = session.post(
                f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{email}:signJwt",
                json={"payload": json.dumps(claims)}, timeout=20)
        except OSError:
            raise WalletError("sign: connection failed") from None
        self._check(response, "sign")
        return SAVE_URL + response.json()["signedJwt"]


class MemoryWalletClient:
    """Keeps objects in memory (tests, local development)."""

    def __init__(self):
        self.objects: dict[str, dict] = {}

    def upsert_object(self, obj: dict) -> None:
        self.objects[obj["id"]] = obj

    def set_state(self, object_id: str, state: str) -> None:
        self.patch_object(object_id, {"state": state})

    def patch_object(self, object_id: str, fields: dict) -> None:
        if object_id not in self.objects:
            raise WalletError("patch: HTTP 404")
        self.objects[object_id].update(fields)

    def save_url(self, object_id: str) -> str:
        return SAVE_URL + "test-" + object_id


@lru_cache
def _google_client() -> GoogleWalletClient:
    return GoogleWalletClient()


def get_wallet() -> WalletClient:
    """FastAPI dependency; tests override it with MemoryWalletClient."""
    return _google_client()
