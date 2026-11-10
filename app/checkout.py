import secrets
from dataclasses import dataclass

from app.desconto_negocio import pricing_snapshot_for_course
from app.pricing import amount_label_for_course


@dataclass
class CheckoutSession:
    token: str
    phone: str
    course_label: str
    amount_label: str = "a partir de R$ 69,90"
    lead_name: str = ""
    confirmed: bool = False
    desconto_pct: int | None = None
    a_vista_label: str | None = None
    total_18_label: str | None = None


_SESSIONS: dict[str, CheckoutSession] = {}


def create_checkout(
    phone: str,
    *,
    course_label: str = "Pós-Graduação EAD Faveni",
    lead_name: str = "",
    amount_label: str | None = None,
    desconto_pct: int | None = None,
    meta: dict | None = None,
) -> CheckoutSession:
    token = secrets.token_urlsafe(16)
    snap = pricing_snapshot_for_course(
        course_label, desconto_pct=desconto_pct, meta=meta
    )
    label = amount_label if amount_label is not None else (
        snap["monthly_label"] or amount_label_for_course(course_label)
    )
    session = CheckoutSession(
        token=token,
        phone=phone,
        course_label=course_label,
        amount_label=label,
        lead_name=lead_name,
        desconto_pct=snap.get("desconto_pct"),
        a_vista_label=snap.get("a_vista_label"),
        total_18_label=snap.get("total_18_label"),
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
