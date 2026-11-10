import secrets
from dataclasses import dataclass

from app.pricing import amount_label_for_course


@dataclass
class CheckoutSession:
    token: str
    phone: str
    course_label: str
    amount_label: str = "a partir de R$ 69,90"
    lead_name: str = ""
    confirmed: bool = False


_SESSIONS: dict[str, CheckoutSession] = {}


def create_checkout(
    phone: str,
    *,
    course_label: str = "Pós-Graduação EAD Faveni",
    lead_name: str = "",
    amount_label: str | None = None,
) -> CheckoutSession:
    token = secrets.token_urlsafe(16)
    label = amount_label if amount_label is not None else amount_label_for_course(course_label)
    session = CheckoutSession(
        token=token,
        phone=phone,
        course_label=course_label,
        amount_label=label,
        lead_name=lead_name,
    )
    _SESSIONS[token] = session
    return session


def get_checkout(token: str) -> CheckoutSession | None:
    return _SESSIONS.get(token)


def confirm_checkout(token: str) -> CheckoutSession | None:
    session = _SESSIONS.get(token)
    if not session:
        return None
    session.confirmed = True
    return session
