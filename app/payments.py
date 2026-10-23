"""Payment provider abstraction.

The roadmap leaves the concrete provider for the business to confirm, so the
app depends only on :class:`PaymentProvider`. :class:`FakePaymentProvider`
behaves like a hosted-checkout provider: it hands out a checkout URL and
later notifies the app through a signed webhook.
"""

import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from .security import sign


@dataclass(frozen=True)
class CheckoutSession:
    reference: str
    checkout_url: str


@dataclass(frozen=True)
class PaymentEvent:
    reference: str
    status: str  # "paid" or "failed"


class PaymentProvider(Protocol):
    name: str

    def create_checkout(self, amount_cents: int, currency: str, description: str) -> CheckoutSession:
        ...

    def parse_webhook(self, body: bytes, signature: str | None) -> PaymentEvent | None:
        """Return the event for a correctly signed notification, else ``None``."""
        ...


class FakePaymentProvider:
    name = "fake"

    def __init__(self, webhook_secret: str):
        self.webhook_secret = webhook_secret

    def create_checkout(self, amount_cents: int, currency: str, description: str) -> CheckoutSession:
        reference = f"fake_{uuid.uuid4().hex}"
        return CheckoutSession(reference, f"https://pay.example.test/checkout/{reference}")

    def sign_event(self, reference: str, status: str) -> tuple[bytes, str]:
        """Build a webhook body and signature, as the provider would send it."""
        body = json.dumps({"reference": reference, "status": status}).encode()
        return body, sign(body, self.webhook_secret)

    def parse_webhook(self, body: bytes, signature: str | None) -> PaymentEvent | None:
        if not signature or not hmac.compare_digest(signature, sign(body, self.webhook_secret)):
            return None
        try:
            data = json.loads(body)
            return PaymentEvent(reference=str(data["reference"]), status=str(data["status"]))
        except (ValueError, KeyError, TypeError):
            return None
