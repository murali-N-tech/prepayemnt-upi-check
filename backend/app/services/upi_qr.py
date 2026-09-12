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

from backend.app.core.upi_limits import cap_for, describe_cap
from backend.app.services.vpa import (
    graded,
    total_weight,
    CANONICAL,
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
    embedded_url: Optional[str] = None
    params: dict[str, str] = field(default_factory=dict)
    findings: list[VpaFinding] = field(default_factory=list)
    vpa_analysis: Optional[VpaAnalysis] = None

    @property
    def score(self) -> int:
        own = total_weight(self.findings)
        return min(100, own + (self.vpa_analysis.score if self.vpa_analysis else 0))

    @property
    def all_findings(self) -> list[VpaFinding]:
        return list(self.findings) + (self.vpa_analysis.findings if self.vpa_analysis else [])


def _to_float(value: str | None) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def canonical_words(name: str) -> str:
    """Lower-case and fold look-alikes, but KEEP word boundaries.

    canonical() strips separators, which is right for comparing one address
    against another and wrong here: the tokens are the evidence.
    """
    return "".join(
        CANONICAL.get(ch, ch) for ch in (name or "").lower()
    )


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
    if amount is not None and amount > 0:
        result.amount = amount
        result.amount_locked = True
    elif amount is not None and amount < 0:
        result.findings.append(
            VpaFinding("negative_amount", "high",
                       f"The QR asks for a negative amount ({amount}). A genuine "
                       f"payment request never does.")
        )

    if not result.payee_vpa:
        result.findings.append(
            VpaFinding("no_payee", "critical",
                       "The QR carries no payee address, so there is nothing to verify.")
        )
        return result

    result.vpa_analysis = analyse_vpa(result.payee_vpa)

    # 4. An off-platform link inside a payment request.
    result.embedded_url = unquote(flat["url"]) if flat.get("url") else None
    if flat.get("url"):
        result.findings.append(
            # Severity info, not high: scam_link.py now analyses this URL
            # properly and scores it in its own family. Scoring it here too
            # counted one fact twice and manufactured "two streams agree".
            VpaFinding("embedded_url", "info",
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
            # Token containment, not character overlap.
            #
            # The old rule scored the fraction of the displayed name's LETTERS
            # found anywhere in the address. Unrelated names share letters, so
            # a long local part covered a short shop name: "Ram Store" against
            # amitsharma123@ybl scored 0.857 and the mismatch - the QR-overlay
            # signature this check exists for - was suppressed. Whether any
            # real word of the name appears in the address is the question
            # actually being asked.
            words = [w for w in re.split(r"[^a-z0-9]+", canonical_words(result.payee_name)) if len(w) >= 3]
            shares_a_word = any(w in local for w in words) or any(
                local[i:i + 4] in shown for i in range(max(len(local) - 3, 0))
            )
            if not shares_a_word:
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

    # 8. An amount UPI cannot carry.
    #    Previously a QR asking for Rs 9,99,99,999 produced exactly one
    #    finding - "the amount is fixed at Rs 99,999,999.00 by the QR", severity
    #    info. A request for more than the network permits cannot be honoured by
    #    any app, so it is not a payment request at all: it is a tampered or
    #    fabricated QR, and that is the whole point of parsing the payload.
    #    Checked here, after mc and sign are known, because a signed merchant QR
    #    in a higher-limit category legitimately goes to Rs 5 lakh.
    if result.amount is not None:
        cap = cap_for(result.merchant_code, result.signed)
        if result.amount > cap:
            result.findings.append(
                VpaFinding("amount_over_upi_limit", "critical",
                           f"This QR demands Rs {result.amount:,.2f}, and UPI does not "
                           f"carry more than {describe_cap(cap)} in one payment. No real "
                           f"payment request looks like this - the QR has been tampered "
                           f"with or fabricated.")
            )

    # 9. Context, not risk.
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
