"""Virtual Payment Address analysis.

Everything else in this project scores the *payer* against their own history.
This module scores the *payee* - the thing a pre-payment check is actually
about. A first-time victim paying a scammer a small amount looks perfectly
normal to a behaviour model; the signal is in the address they are paying.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

# ── PSP handles ────────────────────────────────────────────────────────────
# The suffix after '@' identifies the payment service provider. An address on
# a handle no PSP uses cannot receive money, so it is either a typo or bait.

BANK_HANDLES: set[str] = {
    "okaxis", "oksbi", "okhdfcbank", "okicici",
    "axisbank", "axl", "axisb",
    "sbi", "abfspay",
    "hdfcbank", "hdfcbankjd", "payzapp",
    "icici", "icicibank", "ibl", "pockets",
    "kotak", "kmb", "kmbl",
    "yesbank", "yesbankltd", "ybl", "yapl",
    "idfcbank", "idfcnetc", "indus", "indusind",
    "pnb", "unionbank", "uboi", "united", "cnrb", "cbin", "barodampay",
    "bandhan", "dbs", "federal", "fbl", "rbl", "sib", "csbpay", "jkb",
    "dlb", "kbl", "tjsb", "uco", "ubi", "utbi", "idbi", "iob", "psb",
    "mahb", "cosb", "jsfb", "equitas", "ausfb", "esfb", "fincare",
    "jupiteraxis", "naviaxis", "timecosmos", "waaxis", "waicici", "wasbi",
}

WALLET_HANDLES: set[str] = {
    "paytm", "ptaxis", "ptsbi", "ptyes", "pthdfc",
    "ybl", "ibl", "axl",              # PhonePe
    "okaxis", "oksbi", "okhdfcbank", "okicici",   # Google Pay
    "apl", "yapl", "rapl",            # Amazon Pay
    "upi", "airtel", "airtelpaymentsbank", "freecharge", "fam",
    "mobikwik", "jio", "jiopay", "slice", "slc", "cred", "cnrb",
    "superyes", "seyes", "goaxb", "myicici",
}

KNOWN_HANDLES: set[str] = BANK_HANDLES | WALLET_HANDLES

# ── Impersonation targets ──────────────────────────────────────────────────
# Names scammers put in the local part to look official. Paying "sbi-refund"
# feels safe in a way that paying "rakesh9911" does not.

PROTECTED_NAMES: set[str] = {
    "sbi", "statebank", "hdfc", "hdfcbank", "icici", "icicibank", "axis",
    "axisbank", "kotak", "pnb", "canara", "bankofbaroda", "bob", "unionbank",
    "rbi", "npci", "upi", "bhim",
    "paytm", "phonepe", "googlepay", "gpay", "amazonpay", "mobikwik",
    "irctc", "lic", "epfo", "incometax", "gst", "uidai", "aadhaar", "pmkisan",
    "amazon", "flipkart", "myntra", "swiggy", "zomato", "bigbasket", "jio",
    "airtel", "vodafone", "netflix", "zerodha", "groww", "upstox",
}

# Words that turn a brand name into a lure.
LURE_WORDS: tuple[str, ...] = (
    "support", "helpdesk", "help", "care", "customercare", "service",
    "refund", "refunds", "cashback", "reward", "rewards", "prize", "lottery",
    "winner", "claim", "bonus", "offer", "gift", "lucky",
    "kyc", "verify", "verification", "update", "renew", "reactivate",
    "unblock", "block", "secure", "security", "official", "team",
    "recovery", "settlement", "penalty", "fine", "payment", "collect",
)

# Characters that render alike get folded to one representative, so a
# substituted digit compares equal to the letter it is standing in for.
# Applied to BOTH sides of every comparison: 'sb1support' and 'sbi' + 'support'
# both canonicalise to the same thing.
CANONICAL: dict[str, str] = {
    "0": "o",
    "1": "i", "l": "i",
    "2": "z",
    "3": "e",
    "4": "a",
    "5": "s", "$": "s",
    "6": "g", "9": "g",
    "7": "t",
    "8": "b",
}

_VPA_RE = re.compile(r"^([A-Za-z0-9._\-]{2,256})@([A-Za-z][A-Za-z0-9.\-]{1,63})$")
_PHONE_RE = re.compile(r"^(?:\+?91[\s-]?)?([6-9]\d{9})$")


# Severity weights, shared by every scorer so the bands mean the same thing
# wherever they are applied. "critical" is set above the BLOCK threshold on
# purpose: one critical finding is meant to be decisive on its own.
SEVERITY_WEIGHT: dict[str, int] = {"info": 0, "warn": 12, "high": 35, "critical": 70}


@dataclass
class VpaFinding:
    code: str
    severity: str          # "info" | "warn" | "high" | "critical"
    message: str


@dataclass
class VpaAnalysis:
    raw: str
    normalised: str = ""
    local: str = ""
    handle: str = ""
    valid: bool = False
    handle_known: bool = False
    handle_type: str = "unknown"        # "bank" | "wallet" | "unknown"
    impersonates: Optional[str] = None
    findings: list[VpaFinding] = field(default_factory=list)

    @property
    def score(self) -> int:
        """0-100 contribution to the payee's risk, from the findings."""
        return min(100, sum(SEVERITY_WEIGHT[f.severity] for f in self.findings))


def normalise_vpa(value: str) -> str:
    """Lower-case, strip whitespace and unicode-normalise. NFKC folds the
    look-alike characters that make two different strings render the same."""
    text = unicodedata.normalize("NFKC", (value or "").strip())
    return text.lower()


def canonical(text: str) -> str:
    """Strip separators and fold look-alike characters to one representative."""
    stripped = re.sub(r"[^a-z0-9$]", "", (text or "").lower())
    return "".join(CANONICAL.get(ch, ch) for ch in stripped)


_CANON_NAMES = {canonical(n): n for n in PROTECTED_NAMES}
_CANON_LURES = {canonical(w): w for w in LURE_WORDS}
_CANON_HANDLES = {canonical(h): h for h in KNOWN_HANDLES}


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:      # callers only care about <= 2
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def looks_like_phone(value: str) -> Optional[str]:
    """Return the 10-digit Indian mobile number in `value`, if it is one."""
    m = _PHONE_RE.match(normalise_vpa(value).replace(" ", ""))
    return m.group(1) if m else None


def analyse_vpa(value: str) -> VpaAnalysis:
    raw = (value or "").strip()
    result = VpaAnalysis(raw=raw, normalised=normalise_vpa(raw))

    match = _VPA_RE.match(result.normalised)
    if not match:
        result.findings.append(
            VpaFinding("vpa_malformed", "critical",
                       "This is not a valid UPI ID. A UPI ID looks like name@bank.")
        )
        return result

    result.valid = True
    result.local, result.handle = match.group(1), match.group(2)

    # 1. Is the handle real?
    if result.handle in BANK_HANDLES:
        result.handle_known, result.handle_type = True, "bank"
    elif result.handle in WALLET_HANDLES:
        result.handle_known, result.handle_type = True, "wallet"
    else:
        canon_handle = canonical(result.handle)
        if canon_handle in _CANON_HANDLES:
            # Same shape as a real handle once digits are folded back to letters.
            result.findings.append(
                VpaFinding("handle_confusable", "critical",
                           f"@{result.handle} is built to be mistaken for "
                           f"@{_CANON_HANDLES[canon_handle]} by swapping characters.")
            )
        else:
            near = [h for h in KNOWN_HANDLES if _edit_distance(result.handle, h) == 1]
            if near:
                result.findings.append(
                    VpaFinding("handle_lookalike", "high",
                               f"@{result.handle} is not a real UPI handle, but it is one "
                               f"character away from @{near[0]}.")
                )
            else:
                result.findings.append(
                    VpaFinding("handle_unknown", "warn",
                               f"@{result.handle} is not a handle any known UPI provider uses.")
                )

    # 2. Does the local part impersonate a known name?
    #    Note: the brand name ON ITS OWN is not a risk signal - swiggy@ibl and
    #    irctc@paytm are the real addresses. What marks a fake is the brand
    #    paired with a lure word, or a near-miss spelling of it.
    plain = re.sub(r"[^a-z0-9]", "", result.local)
    folded = canonical(result.local)

    hit = next(
        (
            (canon, original)
            for canon, original in _CANON_NAMES.items()
            if canon and canon in folded
        ),
        None,
    )

    if hit:
        canon_name, name = hit
        remainder = folded.replace(canon_name, "", 1)
        lure = next(
            (orig for canon_lure, orig in _CANON_LURES.items() if canon_lure in remainder),
            None,
        )
        if lure:
            result.impersonates = name
            result.findings.append(
                VpaFinding("brand_lure", "critical",
                           f"Combines the name '{name}' with '{lure}'. Banks, the tax "
                           f"office and companies never collect money from an address "
                           f"like this.")
            )
        elif folded == canon_name:
            result.impersonates = name
            if plain == name:
                # Spelled exactly right. swiggy@ibl and irctc@paytm are real
                # addresses, so this is context for the reader, not a risk score.
                result.findings.append(
                    VpaFinding("brand_claim", "info",
                               f"Presents itself as '{name}'. Real merchant addresses "
                               f"look like this too, so check the payee history below.")
                )
            else:
                # Renders like the brand but is not spelled like it: icicl, sb1,
                # amaz0n. That gap is the whole attack.
                result.findings.append(
                    VpaFinding("brand_confusable", "critical",
                               f"Reads as '{name}' but is spelled '{plain}'. A look-alike "
                               f"address is built exactly this way.")
                )
        elif len(canon_name) >= 5:
            result.impersonates = name
            result.findings.append(
                VpaFinding("brand_embedded", "warn",
                           f"Contains the name '{name}' inside a longer address. "
                           f"Confirm the payee in the official app before paying.")
            )
    else:
        # 3. Near-miss on a protected name (typosquatting).
        for canon_name, name in _CANON_NAMES.items():
            if len(canon_name) >= 5 and _edit_distance(folded, canon_name) == 1:
                result.impersonates = name
                result.findings.append(
                    VpaFinding("brand_typosquat", "critical",
                               f"One character away from '{name}'. This is exactly how a "
                               f"look-alike address is built.")
                )
                break

    # 4. Digits standing in for letters inside a name that would be protected.
    if result.impersonates and any(ch.isdigit() for ch in plain) and folded != plain:
        result.findings.append(
            VpaFinding("confusable_digits", "high",
                       "Digits are standing in for letters, a common way to dodge a "
                       "block list.")
        )

    # 5. Weak structural signals.
    digits = sum(ch.isdigit() for ch in result.local)
    if len(result.local) >= 8 and digits / len(result.local) > 0.6:
        result.findings.append(
            VpaFinding("mostly_digits", "info",
                       "The address is mostly digits, so the name tells you nothing.")
        )

    return result
