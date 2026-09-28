"""Check SMTP login for ess@sss.sk (run in Cloud Shell; never prints the password).

    .venv/bin/python -m ess.tools.smtp_check                     # asks for the password
    ESS_SMTP_PASSWORD="$(gcloud secrets versions access latest --secret=ess-smtp-password)" \\
        .venv/bin/python -m ess.tools.smtp_check                 # checks the stored secret

Both runs print a short fingerprint of the password, so a typed password and the stored secret
can be compared without showing either.
"""

import getpass
import hashlib
import os
import smtplib
import ssl
import sys

from ess.config import get_settings


def fingerprint(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()[:8]


def describe(password: str) -> str:
    notes = [f"length {len(password)}", f"fingerprint {fingerprint(password)}"]
    if password != password.strip():
        notes.append("WARNING: leading/trailing whitespace")
    if not password.isascii():
        notes.append("contains non-ASCII characters")
    if "%" in password:
        notes.append("contains '%' - is it URL-encoded by mistake?")
    return ", ".join(notes)


def main() -> int:
    s = get_settings()
    password = os.environ.get("ESS_SMTP_PASSWORD") or getpass.getpass(f"Password for {s.smtp_user}: ")
    print(f"Server {s.smtp_host}:{s.smtp_port}, user {s.smtp_user}")
    print(f"Password: {describe(password)}")
    context = ssl.create_default_context()
    try:
        if s.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=context, timeout=20)
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
            smtp.starttls(context=context)
        with smtp:
            smtp.ehlo()
            print(f"Server offers AUTH: {smtp.esmtp_features.get('auth', '(none)').strip()}")
            smtp.login(s.smtp_user, password)
            print("OK: login succeeded.")
            return 0
    except smtplib.SMTPAuthenticationError as exc:
        print(f"FAILED: authentication refused ({exc.smtp_code} {exc.smtp_error.decode(errors='replace')})")
    except (OSError, smtplib.SMTPException) as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
