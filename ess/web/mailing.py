"""Rendering and sending e-mails from Jinja2 templates (email/<name>.txt and .html)."""

import logging

from ess.mail import Mail, Mailer, MailError
from ess.web.templates import templates

log = logging.getLogger(__name__)


def render_mail(to: str, subject: str, name: str, attachments=(), **context) -> Mail:
    return Mail(to=to, subject=subject, text=templates.get_template(f"email/{name}.txt").render(context),
                html=templates.get_template(f"email/{name}.html").render(context), attachments=tuple(attachments))


def send(mailer: Mailer | None, mail: Mail) -> bool:
    """Send after the database commit; a failure is logged (without the address) and reported as False."""
    if mailer is None:
        log.warning("E-mail not sent: mailer is not configured")
        return False
    try:
        mailer.send(mail)
        return True
    except MailError:
        return False
