"""Reading the pressure the payer is under.

The rest of this system scores two things: how the payer normally behaves, and
what the payee's account looks like. Measured on our own data those two catch
58.4% of social-engineering fraud at a 1% false-positive budget. The other 40%
is missed for a structural reason - in that fraud class the payer behaves
completely normally, because they were persuaded. The evidence is not in the
transaction. It is in the message that caused the transaction.

This module turns that message into named, inspectable patterns. It does NOT
return an opaque probability, because the explanation is the product: "this
message claims to be your bank, gives you 30 minutes, and tells you not to
discuss it" is something a person can act on. A 0.83 is not.

WHAT MAKES THIS HARD, AND WHY THE WEIGHTS ARE LEARNED
-----------------------------------------------------
Genuine bank messages also say "urgent", "your account will be blocked",
"act immediately", "verify now". A detector that fires on urgency will look
excellent against easy negatives and be worse than useless in practice: it
cries wolf on real bank alerts and teaches people to dismiss the warning.

So authority and urgency are deliberately WEAK evidence here. The patterns
that separate a scam from a real bank SMS are the ones a bank never uses:
asking you to pay a person, to keep it secret, to install something or share
your screen, to send a small amount "to verify", or to move the conversation
to a phone number. The logistic weights in models/coercion_weights.json are
fitted rather than hand-set precisely so this is measured rather than assumed.

The weights are stored as JSON, not a pickle. A scikit-learn pickle is tied to
the numpy version that produced it - this project has already lost an
afternoon to exactly that - and eleven coefficients do not need a binary
format. The JSON is diffable, inspectable, and loads anywhere.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Anchored to the project root, not the process working directory: started
# from anywhere else the weights silently failed to load and a different
# scoring function shipped, with no error anywhere.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEIGHTS_PATH = _PROJECT_ROOT / "models" / "coercion_weights.json"

# Coverage note: English plus the romanised Hindi/Hinglish that appears in
# Indian scam traffic. Devanagari script and other Indian languages are NOT
# covered, and the check says so rather than silently scoring them as clean.
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


@dataclass(frozen=True)
class Pattern:
    """One persuasion tactic, and the words that evidence it."""
    code: str
    label: str
    terms: tuple[str, ...]
    #

    def find(self, text: str) -> list[str]:
        """Every distinct phrase of this pattern present in `text`."""
        hits: list[str] = []
        for term in self.terms:
            match = re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
            if match:
                hits.append(match.group(0))
        return hits


# ── The patterns ──────────────────────────────────────────────────────────────
#
# Grouped by how much a legitimate message might share them. The first group is
# routinely present in real bank SMS; the second group essentially never is.

WEAK_PATTERNS = (
    Pattern("authority", "Claims to be an authority", (
        "bank", "rbi", "reserve bank", "income tax", "police", "cyber cell",
        "officer", "government", "customs", "kyc", "electricity board",
        "court", "legal department", "tax department", "sbi", "npci",
    )),
    Pattern("urgency", "Creates time pressure", (
        "immediately", "urgent", "urgently", "within 30 minutes", "within 1 hour",
        "within 24 hours", "last warning", "final notice", "expires today",
        "act now", "hurry", "turant", "jaldi", "abhi",
    )),
    Pattern("fear", "Threatens a consequence", (
        "will be blocked", "will be suspended", "will be deactivated",
        "penalty", "legal action", "arrest", "fir", "case will be filed",
        "account closed", "band ho jayega", "band kar diya",
    )),
    # Measured precision on the corpus: 68.9%. Every genuine bill reminder
    # says "pay". It was classed STRONG, which let it satisfy the gate below
    # and so defeated the one safeguard this module is built around: an
    # ordinary overdue-bill notice scored 98 and reached BLOCK.
    Pattern("pay_request", "Asks you to send money", (
        "pay", "send money", "transfer", "make payment", "pay now",
        "send rs", "send the amount", "paise bhejo", "payment karo",
        "scan the qr", "scan this qr", "use this upi",
    )),
    # Measured precision: 27.4% - lower than authority. Banks say "never
    # share your OTP" constantly, and this fires on the warning as readily as
    # on the demand. Severity drops with it; claiming "critical" for a cue
    # that is wrong three times in four is not defensible.
    Pattern("credential_request", "Mentions a secret (OTP, PIN, CVV)", (
        "otp", "one time password", "cvv", "pin number", "upi pin",
        "share your pin", "atm pin", "card number", "password",
    )),
)

STRONG_PATTERNS = (
    Pattern("secrecy", "Asks you to keep it quiet", (
        "do not tell", "don't tell", "do not inform", "do not share this",
        "keep this confidential", "between us", "do not discuss",
        "kisi ko mat batao", "confidential matter",
    )),
    Pattern("remote_control", "Wants access to your device", (
        "anydesk", "teamviewer", "quick support", "quicksupport",
        "screen share", "screen sharing", "install the app", "download the apk",
        "remote access", "share your screen",
    )),
    Pattern("verify_payment", "Small payment to 'verify'", (
        "pay 1 rupee", "pay rs 1", "rs.1", "re 1", "small amount to verify",
        "verification charge", "processing fee", "refundable fee",
        "token amount", "activation fee",
    )),
    Pattern("lure", "Offers a reward", (
        "cashback", "lottery", "you have won", "prize", "lucky winner",
        "refund of rs", "double your money", "guaranteed returns",
        "work from home", "part time job", "investment plan",
    )),
    Pattern("contact_offline", "Moves you to a phone number", (
        "call this number", "call immediately on", "whatsapp on",
        "contact us on", "call back on", "helpline number", "call me on",
    )),
)

ALL_PATTERNS: tuple[Pattern, ...] = WEAK_PATTERNS + STRONG_PATTERNS
FEATURE_ORDER: tuple[str, ...] = tuple(p.code for p in ALL_PATTERNS)

# How each pattern is described when it fires, and how loudly.
SEVERITY: dict[str, str] = {
    "authority": "info",
    "urgency": "info",
    "fear": "warn",
    "lure": "warn",
    "pay_request": "info",
    "contact_offline": "warn",
    "secrecy": "high",
    "verify_payment": "high",
    "remote_control": "critical",
    "credential_request": "warn",
}

MAX_MESSAGE_CHARS = 4000

# Weak cues alone cannot raise an alarm, however many of them there are.
#
# This is POLICY, stated here the way the decision thresholds in
# payee_check.py are stated - so a reviewer can argue with it - and it exists
# because the fitted model would not hold the line on its own. In the corpus
# scams almost always carry urgency AND fear, so the model happily learned to
# add those two together and cross the threshold. A genuine overdue-EMI notice
# ("urgent", "immediately", "legal action") then scores 50, and the warning
# fires on a real bank message.
#
# The claim being enforced: a message containing only the cues that legitimate
# institutional messages also contain is not evidence of coercion. Something a
# bank never does - asking you to pay a person, to keep it quiet, to install
# something, to send a token amount, to move to a phone number - has to be
# present before this stream says anything loud.
# Below payee_check's agreement threshold (20) on purpose: a message this
# module has decided is NOT evidence must not then be counted as one of the
# independent streams that agree.
WEAK_ONLY_CEILING = 15


def apply_policy(probability: float, features: dict[str, int]) -> tuple[int, bool]:
    """Turn a fitted probability into the score this system acts on.

    Returns (score, gated). Used by the service AND by the trainer, so the
    metrics in models/coercion_weights.json describe the function that
    actually runs rather than the raw model.
    """
    score = int(round(probability * 100))
    has_strong = any(features[p.code] for p in STRONG_PATTERNS)
    if not has_strong and score > WEAK_ONLY_CEILING:
        return WEAK_ONLY_CEILING, True
    return score, False


@dataclass
class CoercionFinding:
    code: str
    severity: str
    message: str
    quote: Optional[str] = None


@dataclass
class CoercionAnalysis:
    """What the message says about the pressure behind the payment."""
    supplied: bool
    score: int = 0                       # 0-100
    patterns: dict[str, bool] = field(default_factory=dict)
    findings: list[CoercionFinding] = field(default_factory=list)
    probability: float = 0.0
    language_note: Optional[str] = None
    model: str = "unfitted"
    #  True when only weak cues fired and the score was held down by policy.
    weak_only: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "supplied": self.supplied,
            "score": self.score,
            "probability": round(self.probability, 3),
            "patterns": self.patterns,
            "language_note": self.language_note,
            "model": self.model,
            "weak_only": self.weak_only,
            "findings": [
                {"code": f.code, "severity": f.severity, "message": f.message, "quote": f.quote}
                for f in self.findings
            ],
        }


def extract_features(text: str) -> dict[str, int]:
    """The pattern vector. This is the only thing the model ever sees."""
    return {p.code: int(bool(p.find(text))) for p in ALL_PATTERNS}


def _quotes(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in ALL_PATTERNS:
        hits = pattern.find(text)
        if hits:
            out[pattern.code] = hits[0]
    return out


# ── The fitted model ──────────────────────────────────────────────────────────

_weights: Optional[dict[str, Any]] = None


def load_weights(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Coefficients from models/coercion_weights.json, or None if unfitted."""
    global _weights
    if _weights is not None:
        return _weights
    # Read the module attribute at CALL time. As a default argument it was
    # evaluated at import, so pointing WEIGHTS_PATH at a fixture had no effect.
    path = path or WEIGHTS_PATH
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "coefficients" not in data:
        return None
    _weights = data
    return _weights


def reset_weights_cache() -> None:
    """Tests point WEIGHTS_PATH at a fixture and need the cache cleared."""
    global _weights
    _weights = None


def _fallback_probability(features: dict[str, int]) -> float:
    """Used only when no fitted model is present.

    Deliberately conservative and stated as such: the strong patterns carry the
    signal, the weak ones barely move it, because a real bank SMS contains the
    weak ones too.
    """
    strong = sum(features[p.code] for p in STRONG_PATTERNS)
    weak = sum(features[p.code] for p in WEAK_PATTERNS)
    raw = 1.15 * strong + 0.25 * weak - 2.2
    return 1.0 / (1.0 + math.exp(-raw))


def analyse_message(text: Optional[str]) -> CoercionAnalysis:
    """Score a pasted message. Absent or empty input is not evidence of safety."""
    if not text or not text.strip():
        return CoercionAnalysis(supplied=False)

    text = text.strip()[:MAX_MESSAGE_CHARS]
    features = extract_features(text)

    weights = load_weights()
    if weights:
        coeffs = weights["coefficients"]
        raw = float(weights.get("intercept", 0.0)) + sum(
            float(coeffs.get(code, 0.0)) * features[code] for code in FEATURE_ORDER
        )
        probability = 1.0 / (1.0 + math.exp(-raw))
        model = weights.get("trained_at", "fitted")
    else:
        probability = _fallback_probability(features)
        model = "unfitted-fallback"

    score, gated = apply_policy(probability, features)

    quotes = _quotes(text)
    findings = [
        CoercionFinding(
            code=p.code,
            severity=SEVERITY[p.code],
            message=p.label,
            quote=quotes.get(p.code),
        )
        for p in ALL_PATTERNS
        if features[p.code]
    ]

    # A message written in a script we do not cover must not come back clean.
    language_note = None
    if _DEVANAGARI.search(text):
        language_note = (
            "This message is partly in Devanagari script, which these patterns "
            "do not cover. Treat the message result as incomplete."
        )

    if gated:
        findings.append(CoercionFinding(
            "weak_cues_only", "info",
            "This message is urgent or official-sounding, but genuine bank and "
            "biller messages are too. Nothing here is something a real institution "
            "would never do, so this alone is not treated as pressure.",
        ))

    return CoercionAnalysis(
        supplied=True,
        score=score,
        patterns=features,
        findings=findings,
        probability=probability,
        language_note=language_note,
        model=model,
        weak_only=gated,
    )
