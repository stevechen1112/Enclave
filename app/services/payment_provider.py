"""Payment provider abstraction (CG-PAY)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CheckoutRequest:
    tenant_id: str
    plan: str
    amount: int  # TWD dollars
    currency: str = "TWD"
    description: str = ""
    email: str = ""


@dataclass
class CheckoutResult:
    checkout_url: str
    trade_no: str
    form_fields: dict


@dataclass
class WebhookEvent:
    event_type: str  # payment.success | payment.failed
    trade_no: str
    gateway_trade_no: str
    amount: int
    currency: str
    tenant_id: str
    plan: str
    raw: dict


class PaymentProvider(ABC):
    @abstractmethod
    def create_checkout(self, req: CheckoutRequest) -> CheckoutResult: ...

    @abstractmethod
    def verify_webhook(self, payload: dict) -> WebhookEvent: ...
