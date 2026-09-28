"""Phase 2 spike: verify Google Wallet access from Cloud Run without a service account key.

Checks, step by step:
1. the runtime service account can read the existing eCP class (issuer access, setup step 14b),
2. images in the media bucket are publicly readable by exact name, but the bucket cannot be listed,
3. a test pass object for a FICTIONAL member can be created or updated,
4. the "Save to Google Wallet" JWT can be signed through the IAM Credentials API (setup step 14a).

The response contains no secrets; the save link only references the test object.
"""

import io
import json
import os
import secrets
import time

import google.auth
import requests
from fastapi import FastAPI
from google.auth.transport.requests import AuthorizedSession, Request
from PIL import Image, ImageDraw

app = FastAPI()

ISSUER_ID = os.environ.get("WALLET_ISSUER_ID", "3388000000022877308")
CLASS_SUFFIX = os.environ.get("WALLET_CLASS", "member")
BUCKET = os.environ.get("MEDIA_BUCKET", "")
WALLET_API = "https://walletobjects.googleapis.com/walletobjects/v1"
GCS = "https://storage.googleapis.com"
TEST_OBJECT_SUFFIX = "ess_probe_test"


def _session(scope: str) -> tuple[AuthorizedSession, str]:
    credentials, _ = google.auth.default(scopes=[scope])
    credentials.refresh(Request())
    return AuthorizedSession(credentials), getattr(credentials, "service_account_email", "?")


def _error(response: requests.Response) -> str:
    try:
        return response.json().get("error", {}).get("message", "")[:300]
    except ValueError:
        return response.text[:300]


def _placeholder_photo() -> bytes:
    """Neutral silhouette instead of a real face (never use real personal data in tests)."""
    image = Image.new("RGB", (300, 400), "#d9d9d9")
    draw = ImageDraw.Draw(image)
    draw.ellipse((95, 60, 205, 190), fill="#8c8c8c")
    draw.ellipse((40, 210, 260, 480), fill="#8c8c8c")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _upload_photo() -> str:
    from google.cloud import storage

    name = f"probe/{secrets.token_hex(32)}.png"  # 64 random hex characters, as for real photos
    blob = storage.Client().bucket(BUCKET).blob(name)
    blob.upload_from_string(_placeholder_photo(), content_type="image/png")
    return f"{GCS}/{BUCKET}/{name}"


def _check_public(url: str) -> int:
    return requests.get(url, timeout=10).status_code  # anonymous request, like Google Wallet


def _pass_object(object_id: str, class_id: str, photo_url: str) -> dict:
    valid_until = f"31.12.{time.gmtime().tm_year}"
    text = lambda value: {"defaultValue": {"language": "sk", "value": value}}  # noqa: E731
    return {
        "id": object_id,
        "classId": class_id,
        "state": "ACTIVE",
        "logo": {"sourceUri": {"uri": f"{GCS}/{BUCKET}/static/Logo_sss.png"}},
        "cardTitle": text("Slovenská speleologická spoločnosť"),
        "header": text("Ján Skúšobný (TEST)"),
        "wideLogo": {"sourceUri": {"uri": f"{GCS}/{BUCKET}/static/SSS_logo_meno.png"}},
        "barcode": {"type": "QR_CODE", "value": "https://www.speleology.sk/?ess-probe",
                    "alternateText": f"Platnosť do {valid_until}"},
        "imageModulesData": [{"id": "photo", "mainImage": {"sourceUri": {"uri": photo_url}}}],
        # Module ids as in the original design (wallet_layout_config.json); the class template may use them.
        "textModulesData": [
            {"id": "primary_club", "header": "Klub", "body": "Testovacia skupina"},
            {"id": "member_from", "header": "Členom od", "body": "01.01.2000"},
            {"id": "member_id", "header": "Identifikačné číslo", "body": "TEST-0001"},
            {"id": "birth_date", "header": "Dátum narodenia", "body": "01.01.1980"},
            {"id": "valid_until", "header": "Platný do", "body": valid_until},
        ],
        "linksModuleData": {"uris": [{"id": "homepage", "uri": "https://www.speleology.sk", "description": "Web SSS"}]},
    }


@app.get("/probe")
def probe() -> dict:
    result: dict = {"ok": False}
    if not BUCKET:
        result["error"] = "MEDIA_BUCKET is not set"
        return result

    wallet, sa_email = _session("https://www.googleapis.com/auth/wallet_object.issuer")
    result["service_account"] = sa_email
    class_id = f"{ISSUER_ID}.{CLASS_SUFFIX}"
    object_id = f"{ISSUER_ID}.{TEST_OBJECT_SUFFIX}"

    # 1. Issuer access: read the existing class.
    response = wallet.get(f"{WALLET_API}/genericClass/{class_id}")
    result["class"] = {"http": response.status_code}
    if response.ok:
        result["class"]["review_status"] = response.json().get("reviewStatus")
    else:
        result["class"]["error"] = _error(response)
        result["hint"] = "403 = service account is not a user of the issuer (step 14b); 404 = wrong class id"
        return result

    # 2. Images: readable by exact name, bucket listing refused.
    try:
        photo_url = _upload_photo()
    except Exception as exc:  # noqa: BLE001 - report any storage problem
        result["photo_upload"] = f"failed: {type(exc).__name__}"
        return result
    result["images_http"] = {
        "logo": _check_public(f"{GCS}/{BUCKET}/static/Logo_sss.png"),
        "wide_logo": _check_public(f"{GCS}/{BUCKET}/static/SSS_logo_meno.png"),
        "photo": _check_public(photo_url),
        "bucket_listing": _check_public(f"{GCS}/{BUCKET}"),  # must be 401 or 403
    }

    # 3. Create or replace the test object.
    body = _pass_object(object_id, class_id, photo_url)
    response = wallet.post(f"{WALLET_API}/genericObject", json=body)
    if response.status_code == 409:
        response = wallet.put(f"{WALLET_API}/genericObject/{object_id}", json=body)
    result["object"] = {"http": response.status_code}
    if not response.ok:
        result["object"]["error"] = _error(response)
        return result

    # 4. Sign the "Save to Google Wallet" JWT without a key file.
    iam, _ = _session("https://www.googleapis.com/auth/cloud-platform")
    claims = {"iss": sa_email, "aud": "google", "typ": "savetowallet", "iat": int(time.time()),
              "origins": [], "payload": {"genericObjects": [{"id": object_id}]}}
    response = iam.post(
        f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{sa_email}:signJwt",
        json={"payload": json.dumps(claims)},
    )
    result["sign_jwt"] = {"http": response.status_code}
    if not response.ok:
        result["sign_jwt"]["error"] = _error(response)
        result["hint"] = "403 = missing roles/iam.serviceAccountTokenCreator (step 14a)"
        return result

    result["save_url"] = f"https://pay.google.com/gp/v/save/{response.json()['signedJwt']}"
    result["ok"] = True
    return result
