from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import html
import smtplib
import ssl


class MailerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MailSettings:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    mode: str
    public_base_url: str

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.from_email and self.public_base_url)


class SMTPMailer:
    def __init__(self, settings: MailSettings) -> None:
        self.settings = settings

    def _connect(self):
        cfg = self.settings
        if not cfg.enabled:
            raise MailerError("SMTP/öffentliche Basis-URL ist nicht vollständig konfiguriert")
        if cfg.mode not in {"starttls", "ssl"}:
            raise MailerError("Unsicherer SMTP-Modus wurde verweigert")
        context = ssl.create_default_context()
        if cfg.mode == "ssl":
            client = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20, context=context)
        else:
            client = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
            client.ehlo()
            if cfg.mode == "starttls":
                client.starttls(context=context)
                client.ehlo()
        if cfg.username:
            client.login(cfg.username, cfg.password)
        return client

    def send(self, *, to_email: str, subject: str, text: str, reply_to: str | None = None) -> None:
        cfg = self.settings
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{cfg.from_name} <{cfg.from_email}>" if cfg.from_name else cfg.from_email
        msg["To"] = to_email
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(text)
        safe_html = "<br>".join(html.escape(line) for line in text.splitlines())
        msg.add_alternative(f"<html><body><p>{safe_html}</p></body></html>", subtype="html")
        try:
            with self._connect() as client:
                client.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailerError(f"E-Mail-Versand fehlgeschlagen: {exc}") from exc
