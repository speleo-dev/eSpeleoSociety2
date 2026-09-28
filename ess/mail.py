"""Outgoing e-mail through the WebSupport SMTP server (ess@sss.sk).

Recipients' addresses are personal data: they are never logged, and errors are reported
without the address.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from functools import lru_cache
from typing import Protocol

from ess.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str | None = None


class MailError(Exception):
    """Sending failed; the message never contains the recipient's address."""


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class SmtpMailer:
    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    def _message(self, mail: Mail) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = mail.to
        msg["Subject"] = mail.subject
        msg["Message-ID"] = make_msgid(domain=self.user.rsplit("@", 1)[-1])
        msg.set_content(mail.text)
        if mail.html:
            msg.add_alternative(mail.html, subtype="html")
        return msg

    def send(self, mail: Mail) -> None:
        context = ssl.create_default_context()
        try:
            if self.port == 465:
                smtp = smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=20)
            else:
                smtp = smtplib.SMTP(self.host, self.port, timeout=20)
                smtp.starttls(context=context)
            with smtp:
                smtp.login(self.user, self.password)
                smtp.send_message(self._message(mail))
        except (OSError, smtplib.SMTPException) as exc:
            log.warning("SMTP send failed: %s", type(exc).__name__)
            raise MailError(type(exc).__name__) from None


class MemoryMailer:
    """Collects messages instead of sending them (tests, local development)."""

    def __init__(self):
        self.sent: list[Mail] = []

    def send(self, mail: Mail) -> None:
        self.sent.append(mail)


@lru_cache
def _smtp_mailer(host: str, port: int, user: str, password: str, sender: str) -> SmtpMailer:
    return SmtpMailer(host, port, user, password, sender)


def get_mailer() -> Mailer | None:
    """Configured mailer, or None when ESS_SMTP_PASSWORD is not set (FastAPI dependency)."""
    s = get_settings()
    if not s.smtp_password:
        return None
    return _smtp_mailer(s.smtp_host, s.smtp_port, s.smtp_user, s.smtp_password, s.mail_from)
