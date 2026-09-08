"""UPI QR / deep-link parsing.

A UPI QR code is not an image secret: it encodes a deep link,

    upi://pay?pa=<vpa>&pn=<name>&am=<amount>&tn=<note>&url=<link>

The attacks that matter here are the ones a person cannot see by looking at
the QR: a sticker pasted over a shop's real code, a display name that does
not belong to the address being paid, or an off-platform link smuggled in
the url parameter. Parsing the payload is what catches those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, unquote, urlsplit

from backend.app.services.vpa import (
    SEVERITY_WEIGHT,
    VpaAnalysis,
    VpaFinding,
    analyse_vpa,
    canonical,
    looks_like_phone,
)

# Schemes that legitimately carry a UPI payment request.
UPI_SCHEMES = {"upi", "bhim", "phonepe", "paytmmp", "gpay", "tez"}

# Everything the spec defines, so an unexpected parameter can be spotted.
KNOWN_PARAMS = {
    "pa", "pn", "mc", "tid", "tr", "tn", "am", "mam", "cu",
    "url", "mode", "purpose", "orgid", "sign", "qrmedium", "featuretype",
}


@dataclass
class QrAnalysis:
    raw: str
    kind: str = "unknown"        # "deep_link" | "vpa" | "phone" | "unknown"
    payee_vpa: Optional[str] = None
    payee_name: Optional[str] = None
    amount: Optional[float] = None
    amount_locked: bool = False
    note: Optional[str] = None
    merchant_code: Optional[str] = None
    signed: bool = False
    params: dict[str, str] = field(default_factory=dict)
    findings: list[VpaFinding] = field(default_factory=list)
    vpa_analysis: Optional[VpaAnalysis] = None

    @property
    def score(self) -> int:
        own = sum(SEVERITY_WEIGHT[f.severity] for f in self.findings)
        return min(100, own + (self.vpa_analysis.score if self.vpa_analysis else 0))

    @property
    def all_findings(self) -> list[VpaFinding]:
        return list(self.findings) + (self.vpa_analysis.findings if self.vpa_analysis else [])


def _to_float(value: str | None) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_upi_target(payload: str) -> QrAnalysis:
    """Accepts a scanned QR payload, a pasted UPI ID, or a phone number."""
    raw = (payload or "").strip()
    result = QrAnalysis(raw=raw)

    if not raw:
        result.findings.append(
            VpaFinding("empty", "critical", "Nothing to check - paste a UPI ID or QR contents.")
        )
        return result

    # 1. A bare phone number: valid for UPI, but it resolves to whoever
    #    currently holds the number, so the display name cannot be checked.
    phone = looks_like_phone(raw)
    if phone and "@" not in raw and "://" not in raw:
        result.kind = "phone"
        result.payee_vpa = f"{phone}@upi"
        result.findings.append(
            VpaFinding("phone_target", "warn",
                       "Paying a phone number sends money to whoever holds that number "
                       "today. Confirm the name your app shows before approving.")
        )
        result.vpa_analysis = analyse_vpa(result.payee_vpa)
        return result

    # 2. A pasted UPI ID.
    if "://" not in raw:
        result.kind = "vpa"
        result.payee_vpa = raw
        result.vpa_analysis = analyse_vpa(raw)
        return result

    # 3. A deep link.
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()

    if scheme not in UPI_SCHEMES:
        result.findings.append(
            VpaFinding("not_a_payment_link", "critical",
                       f"This QR opens a {scheme}:// link, not a UPI payment. A payment "
                       f"QR always starts with upi://. Do not open it.")
        )
        return result

    result.kind = "deep_link"
    # urlsplit puts everything after 'upi://pay' in .query for these links.
    query = parts.query or parts.path.partition("?")[2]
    flat = {k: v[0] for k, v in parse_qs(query, keep_blank_values=True).items()}
    result.params = flat

    result.payee_vpa = (flat.get("pa") or "").strip()
    result.payee_name = unquote(flat.get("pn", "")).strip() or None
    result.note = unquote(flat.get("tn", "")).strip() or None
    result.merchant_code = flat.get("mc") or None
    result.signed = bool(flat.get("sign"))

    amount = _to_float(flat.get("am"))
    if amount is not None:
        result.amount = amount
        result.amount_locked = True

    if not result.payee_vpa:
        result.findings.append(
            VpaFinding("no_payee", "critical",
                       "The QR carries no payee address, so there is nothing to verify.")
        )
        return result

    result.vpa_analysis = analyse_vpa(result.payee_vpa)

    # 4. An off-platform link inside a payment request.
    if flat.get("url"):
        result.findings.append(
            VpaFinding("embedded_url", "high",
                       f"The QR carries a link ({unquote(flat['url'])[:60]}). A payment "
                       f"request does not need one, and opening it is how credentials "
                       f"get taken.")
        )

    # 5. Display name that does not match the address being paid. This is the
    #    signature of a sticker pasted over a real shop's QR.
    if result.payee_name and result.vpa_analysis and result.vpa_analysis.valid:
        local = canonical(result.vpa_analysis.local)
        shown = canonical(result.payee_name)
        if shown and local and shown not in local and local not in shown:
            overlap = len(set(shown) & set(local)) / max(len(set(shown)), 1)
            if overlap < 0.75:
                result.findings.append(
                    VpaFinding("name_mismatch", "high",
                               f"The QR displays '{result.payee_name}' but pays "
                               f"'{result.payee_vpa}'. Those do not look like the same "
                               f"person or business.")
                )

    # 6. Currency other than rupees.
    currency = (flat.get("cu") or "INR").upper()
    if currency != "INR":
        result.findings.append(
            VpaFinding("currency", "warn", f"The request is in {currency}, not INR.")
        )

    # 7. Parameters outside the UPI spec.
    unknown = sorted(set(flat) - KNOWN_PARAMS)
    if unknown:
        result.findings.append(
            VpaFinding("unknown_params", "warn",
                       f"Carries parameters that are not part of the UPI spec: "
                       f"{', '.join(unknown[:4])}.")
        )

    # 8. Context, not risk.
    if result.amount_locked:
        result.findings.append(
            VpaFinding("amount_locked", "info",
                       f"The amount is fixed at Rs {result.amount:,.2f} by the QR - you "
                       f"cannot change it in your app.")
        )
    if result.signed and result.merchant_code:
        result.findings.append(
            VpaFinding("signed_merchant", "info",
                       "Carries a merchant code and a signature, which an individual "
                       "scammer's QR normally does not.")
        )

    return result
