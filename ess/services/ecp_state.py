"""eCP state follows SSS membership (R25).

- member of SSS (an open membership with status `member`)  -> `active`
- left all clubs, waiting for the administrator's decision -> still `active` (a club decides only for
  itself; the member may have paid the SSS fee, R30)
- suspended in every club where the member still is -> `inactive`
- expelled or SSS membership ended -> `revoked` (final)

The state is recalculated automatically whenever a member or a membership changes (SQLAlchemy flush
events), so no service can forget it. Google Wallet is updated after the commit by `push_pending`
(passes whose `wallet_state` differs from `state`); a failed push is retried on the next call.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ess import audit
from ess.models import EcpPass, EcpPassState, Member, Membership, MembershipStatus
from ess.wallet import WalletClient, WalletError

log = logging.getLogger(__name__)
_KEY = "ecp_state_members"

WALLET_STATES = {EcpPassState.ACTIVE.value: "ACTIVE", EcpPassState.INACTIVE.value: "INACTIVE",
                 EcpPassState.REVOKED.value: "EXPIRED"}


def desired_state(session: Session, member: Member) -> str:
    if member.expelled_at or member.sss_ended_at:
        return EcpPassState.REVOKED.value
    statuses = set(session.scalars(select(Membership.status).where(
        Membership.member_id == member.id, Membership.valid_to.is_(None))))
    if not statuses or MembershipStatus.MEMBER in statuses:
        return EcpPassState.ACTIVE.value
    return EcpPassState.INACTIVE.value


def refresh(session: Session, member_id: uuid.UUID) -> None:
    ecp_pass = session.scalar(select(EcpPass).where(EcpPass.member_id == member_id,
                                                    EcpPass.state != EcpPassState.REVOKED.value))
    if ecp_pass is None:
        return
    new = desired_state(session, session.get(Member, member_id))
    if new == ecp_pass.state:
        return
    old, ecp_pass.state = ecp_pass.state, new
    if new == EcpPassState.REVOKED.value:
        ecp_pass.revoked_at = datetime.now(UTC)
    audit.record(session, actor_type="system", actor_id="system", action="ecp.state",
                 entity_type="ecp_pass", entity_id=str(ecp_pass.id), details={"from": old, "to": new})


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _flush_context) -> None:
    ids = session.info.setdefault(_KEY, set())
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Membership):
            ids.add(obj.member_id)
        elif isinstance(obj, Member):
            ids.add(obj.id)


@event.listens_for(Session, "after_flush_postexec")
def _apply(session: Session, _flush_context) -> None:
    ids = session.info.pop(_KEY, set())
    for member_id in ids:
        if member_id is not None:
            refresh(session, member_id)


def _pending_query():
    return select(EcpPass).where((EcpPass.wallet_state.is_(None)) | (EcpPass.wallet_state != EcpPass.state))


def has_pending(session: Session) -> bool:
    return session.scalar(_pending_query().with_only_columns(EcpPass.id).limit(1)) is not None


def push_pending(session: Session, wallet: WalletClient, store=None) -> int:
    """Send changed states to Google Wallet. Commits each pass separately; returns the number pushed."""
    pending = session.scalars(_pending_query()).all()
    done = 0
    for ecp_pass in pending:
        try:
            if ecp_pass.state == EcpPassState.REVOKED.value:
                # No personal data stays in the wallet; the QR keeps pointing to the warning page.
                wallet.patch_object(ecp_pass.wallet_object_id, {
                    "state": "EXPIRED",
                    "header": {"defaultValue": {"language": "sk", "value": "Neplatný preukaz"}},
                    "textModulesData": [], "imageModulesData": []})
            else:
                wallet.set_state(ecp_pass.wallet_object_id, WALLET_STATES[ecp_pass.state])
        except WalletError:
            log.warning("eCP state not pushed to Google Wallet; will retry")
            continue
        photo = ecp_pass.photo if ecp_pass.state == EcpPassState.REVOKED.value else None
        if photo:
            ecp_pass.photo = None
        ecp_pass.wallet_state = ecp_pass.state
        session.commit()
        if photo and store:
            store.delete(photo)
        done += 1
    return done
