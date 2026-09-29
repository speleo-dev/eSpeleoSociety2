"""E-mails prepared by services and sent by the web layer only after the transaction commits.

Services call `queue()`; the web layer calls `take()` after `session.commit()` and discards the queue
on rollback, so no e-mail refers to data that was not saved.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

_KEY = "outbox"


@dataclass
class QueuedMail:
    to: str
    subject: str
    template: str  # templates/email/<template>.txt and .html
    context: dict = field(default_factory=dict)  # "link_path" is completed with the public base URL


def queue(session: Session, mail: QueuedMail) -> None:
    session.info.setdefault(_KEY, []).append(mail)


def take(session: Session) -> list[QueuedMail]:
    return session.info.pop(_KEY, [])


def discard(session: Session) -> None:
    session.info.pop(_KEY, None)
