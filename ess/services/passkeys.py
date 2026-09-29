"""Passkeys (WebAuthn) for the member portal (R38): register after an e-mail code login, then log in with
a fingerprint or face. The challenge lives in the browser's signed session; only public keys are stored.

The relying party is the public address of the application (`base_url`): its host is the RP id and its
scheme + host the expected origin.
"""

import json
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import webauthn
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ess import audit
from ess.models import Member, MemberPasskey
from ess.services import members, portal_auth
from ess.services.access import DomainError

RP_NAME = "eSS – Slovenská speleologická spoločnosť"


def _rp(base_url: str) -> tuple[str, str]:
    parts = urlsplit(base_url)
    return parts.hostname or "", f"{parts.scheme}://{parts.netloc}"


def count(session: Session, member_id: uuid.UUID) -> int:
    return len(session.scalars(select(MemberPasskey.id).where(MemberPasskey.member_id == member_id)).all())


def registration_options(session: Session, member: Member, base_url: str) -> tuple[str, bytes]:
    """Options for navigator.credentials.create() (JSON) and the challenge to keep in the session."""
    rp_id, _ = _rp(base_url)
    data = members.read_member(member)
    existing = session.scalars(select(MemberPasskey.credential_id).where(MemberPasskey.member_id == member.id)).all()
    options = webauthn.generate_registration_options(
        rp_id=rp_id, rp_name=RP_NAME, user_id=member.id.bytes, user_name=data.full_name(),
        user_display_name=data.full_name(),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing])
    return webauthn.options_to_json(options), options.challenge


def register(session: Session, member: Member, credential: str, challenge: bytes, base_url: str) -> MemberPasskey:
    rp_id, origin = _rp(base_url)
    try:
        verified = webauthn.verify_registration_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origin,
            require_user_verification=True)
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError):
        raise DomainError("passkey_failed") from None
    passkey = MemberPasskey(id=uuid.uuid4(), member_id=member.id, credential_id=verified.credential_id,
                            public_key=verified.credential_public_key, sign_count=verified.sign_count)
    session.add(passkey)
    audit.record(session, actor_type="member", actor_id=str(member.id), action="portal.passkey_add",
                 entity_type="member", entity_id=str(member.id))
    return passkey


def authentication_options(session: Session, base_url: str, key: str | None = None) -> tuple[str, bytes]:
    """With the eCP link the member's passkeys are offered; without it the browser offers any saved one."""
    rp_id, _ = _rp(base_url)
    allow = []
    if key:
        ecp_pass = portal_auth.pass_for_key(session, key)
        if ecp_pass is not None:
            allow = [PublicKeyCredentialDescriptor(id=c) for c in session.scalars(
                select(MemberPasskey.credential_id).where(MemberPasskey.member_id == ecp_pass.member_id))]
    options = webauthn.generate_authentication_options(
        rp_id=rp_id, allow_credentials=allow, user_verification=UserVerificationRequirement.REQUIRED)
    return webauthn.options_to_json(options), options.challenge


def authenticate(session: Session, credential: str, challenge: bytes, base_url: str) -> portal_auth.NewSession | str:
    """Returns the new session, or an error code ("passkey_failed", "portal_not_available")."""
    rp_id, origin = _rp(base_url)
    try:
        credential_id = base64url_to_bytes(json.loads(credential)["rawId"])
    except (ValueError, KeyError, TypeError):
        return "passkey_failed"
    passkey = session.scalar(select(MemberPasskey).where(MemberPasskey.credential_id == credential_id))
    if passkey is None:
        return "passkey_failed"
    try:
        verified = webauthn.verify_authentication_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=passkey.public_key, credential_current_sign_count=passkey.sign_count,
            require_user_verification=True)
    except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError):
        return "passkey_failed"
    if not portal_auth.may_log_in(session, passkey.member_id):
        return "portal_not_available"
    passkey.sign_count, passkey.last_used_at = verified.new_sign_count, datetime.now(UTC)
    return portal_auth.open_session(session, passkey.member_id, "passkey")


def delete_all(session: Session, member_id: uuid.UUID) -> int:
    rows = session.scalars(select(MemberPasskey).where(MemberPasskey.member_id == member_id)).all()
    for row in rows:
        session.delete(row)
    return len(rows)


