"""
mailer.py  -  Optional e-mail publishing for Telltale.

The full SMTP send path is built and ready. It reads SMTP credentials from
config/email_config.ini, which ships EMPTY/commented: until you fill it in,
`is_configured()` is False and `send()` is a safe no-op that returns a clear
"not configured" status (the CLI surfaces this as a visible warning on publish
and otherwise carries on normally). No third-party dependencies -- stdlib only.
"""
from __future__ import annotations

import configparser
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from . import config, db


REQUIRED = ("host", "port", "username", "password", "from_addr")


def _read_ini() -> dict:
    cfg = configparser.ConfigParser()
    if not os.path.exists(config.EMAIL_CONFIG_PATH):
        return {}
    cfg.read(config.EMAIL_CONFIG_PATH)
    if not cfg.has_section("smtp"):
        return {}
    return {k: v.strip() for k, v in cfg.items("smtp")}


def is_configured() -> tuple[bool, str]:
    """(ready, reason). ready is False whenever a required field is blank."""
    s = _read_ini()
    if not s:
        return False, "config/email_config.ini has no [smtp] section yet."
    missing = [k for k in REQUIRED if not s.get(k)]
    if missing:
        return False, f"email_config.ini is missing: {', '.join(missing)}."
    return True, "configured"


def recipients() -> list[str]:
    raw = db.get_setting("email_recipients", "") or ""
    return [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]


def send(subject: str, body: str, attachments: list[str] | None = None,
         to: list[str] | None = None) -> tuple[bool, str]:
    """Send an e-mail with optional file attachments.

    Returns (sent, message). When e-mail is not configured this is a no-op that
    returns (False, <reason>) -- it never raises, so publishing a result can
    always proceed."""
    ready, reason = is_configured()
    if not ready:
        return False, reason
    to = to or recipients()
    if not to:
        return False, "no recipients set (Settings -> email recipients)."

    s = _read_ini()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.get("from_addr") or s.get("username")
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)

    for path in (attachments or []):
        if not path or not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        sub = "pdf" if path.lower().endswith(".pdf") else "png"
        maintype = "application" if sub == "pdf" else "image"
        msg.add_attachment(data, maintype=maintype, subtype=sub,
                           filename=os.path.basename(path))

    host, port = s["host"], int(s["port"])
    use_ssl = s.get("use_ssl", "").lower() in ("1", "true", "yes")
    use_tls = s.get("use_tls", "true").lower() in ("1", "true", "yes")
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as srv:
                srv.login(s["username"], s["password"])
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as srv:
                if use_tls:
                    srv.starttls(context=ssl.create_default_context())
                srv.login(s["username"], s["password"])
                srv.send_message(msg)
    except Exception as exc:  # noqa: BLE001  - report, never crash the app
        return False, f"send failed: {exc}"
    return True, f"sent to {', '.join(to)}"
