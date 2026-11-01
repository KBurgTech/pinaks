"""Provider-neutral delivery contract and deployment-configured SMTP adapter."""

import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email


@dataclass(frozen=True)
class Message:
    identity: str
    recipients: tuple[str, ...]
    subject: str
    body: str
    language: str
    created_at: datetime
    attachment: bytes


@dataclass(frozen=True)
class DeliveryResult:
    outcome: str
    failure_code: str = ""
    response_code: int | None = None
    retryable: bool = False


class EmailSender(Protocol):
    def send(self, message: Message) -> DeliveryResult: ...


class SMTPSender:
    def send(self, message: Message) -> DeliveryResult:
        handing_off = False
        client: smtplib.SMTP | None = None
        try:
            if settings.SMTP_USE_TLS and settings.SMTP_USE_SSL:
                raise ImproperlyConfigured("smtp_transport")
            timeout = float(settings.SMTP_TIMEOUT)
            if not 0 < timeout <= 30:
                raise ImproperlyConfigured("smtp_timeout")
            validate_email(settings.SMTP_FROM_EMAIL)
            if any(c in settings.SMTP_FROM_EMAIL for c in "\r\n"):
                raise ImproperlyConfigured("smtp_sender")
            mime = EmailMessage(policy=SMTP)
            mime["From"] = settings.SMTP_FROM_EMAIL
            mime["To"] = ", ".join(message.recipients)
            mime["Subject"] = message.subject
            mime["Date"] = format_datetime(message.created_at)
            mime["Message-ID"] = f"<{message.identity}@pinaks.invalid>"
            mime.set_content(message.body)
            mime.add_attachment(
                message.attachment, maintype="application", subtype="pdf", filename="invoice.pdf"
            )
            if settings.SMTP_USE_SSL:
                client = smtplib.SMTP_SSL(
                    settings.SMTP_HOST,
                    settings.SMTP_PORT,
                    timeout=timeout,
                    context=ssl.create_default_context(),
                )
            else:
                client = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
            if settings.SMTP_USE_TLS:
                client.starttls(context=ssl.create_default_context())
            if settings.SMTP_USERNAME:
                client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            mime["Content-Language"] = message.language
            handing_off = True
            refused = client.send_message(mime)
            if refused:
                # Some recipients accepted: retrying the envelope would duplicate them.
                return DeliveryResult("failed", "partial_delivery")
            return DeliveryResult("sent", response_code=250)
        except smtplib.SMTPRecipientsRefused as error:
            codes = [int(value[0]) for value in error.recipients.values()]
            retryable = all(400 <= code < 500 for code in codes)
            return DeliveryResult(
                "failed", "smtp_transient" if retryable else "smtp_permanent", min(codes), retryable
            )
        except smtplib.SMTPResponseException as error:
            code = error.smtp_code
            retryable = 400 <= code < 500
            return DeliveryResult(
                "failed", "smtp_transient" if retryable else "smtp_permanent", code, retryable
            )
        except (OSError, smtplib.SMTPServerDisconnected):
            if handing_off:
                return DeliveryResult("unknown", "delivery_unknown")
            return DeliveryResult("failed", "smtp_unavailable", retryable=True)
        except (ValueError, smtplib.SMTPException, ImproperlyConfigured, ValidationError):
            return DeliveryResult("failed", "smtp_configuration")
        finally:
            # QUIT failure after a successful DATA response must never cause a resend.
            if client is not None:
                client.close()


def get_sender(key: str) -> EmailSender:
    if key != settings.EMAIL_SENDER_KEY:
        raise ImproperlyConfigured("unknown_sender")
    return SMTPSender()
