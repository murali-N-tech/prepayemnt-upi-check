"""One way to decide whether two payee labels mean the same payee.

Statement text is not consistent. The same person appears as
"CHINTHADA MURALI NAGARAJU", "Chinthada Murali Nagaraju" and
"CHINTHADAMURALINAGARAJU" across statements, and a bank line may carry only a
masked account number. Matching those with `==` means the "merchant has not
appeared before" rule (+20 points, the second heaviest in the engine) fires on
ordinary repeat payments, and every P2P payment drifts toward MEDIUM.

The VPA is the stable identifier. The display name is a label, so it is only
used when there is no VPA, and then it is canonicalised first.
"""

from __future__ import annotations

import re

from backend.app.services.vpa import normalise_vpa

# Terms that carry no identity: two different shops both called
# "SRI ... TRADERS PVT LTD" should not merge, but the suffix should not be the
# thing that makes them match either.
_NOISE = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|co|company|and|the|"
    r"stores?|store|shop|traders?|enterprises?|services?|solutions?|"
    r"mr|mrs|ms|dr|shri|sri|smt)\b",
    re.IGNORECASE,
)

# Masked account fragments a bank statement leaves in the payee column.
_MASKED = re.compile(r"^(x+\d+|\*+\d+|\d{2,}x+\d*)$", re.IGNORECASE)


def is_masked_account(name: str) -> bool:
    """True for placeholders like 'XX1468' that identify nobody."""
    return bool(_MASKED.match((name or "").strip()))


def normalise_merchant(name: str | None) -> str:
    """Canonical form of a display name, for comparison only.

    Never shown to the user: the original spelling is what they recognise.
    """
    text = (name or "").strip().lower()
    if not text:
        return ""
    text = _NOISE.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def merchant_key(merchant: str | None = None, upi_id: str | None = None) -> str:
    """Stable identity for a payee.

    Prefers the VPA, which is the actual account. Falls back to the
    canonicalised display name, and returns "" for a masked account number,
    which is not an identity at all - treating every "XX1468" as the same
    payee would merge unrelated counterparties.
    """
    vpa = normalise_vpa(upi_id or "")
    if vpa and "@" in vpa:
        return vpa
    if is_masked_account(merchant or ""):
        return ""
    slug = normalise_merchant(merchant)
    return f"name:{slug}" if slug else ""


def known_merchant_keys(transactions) -> list[str]:
    """Every payee identity in a user's history, de-duplicated."""
    keys = set()
    for tx in transactions:
        if hasattr(tx, "get"):
            key = merchant_key(tx.get("merchant"), tx.get("upi_id"))
        else:
            key = merchant_key(getattr(tx, "merchant", None), getattr(tx, "upi_id", None))
        if key:
            keys.add(key)
    return sorted(keys)
