"""The scam-link half of "Scam Link / QR Identifier".

The QR half already existed: upi_qr.py parses a upi:// payload and catches a
tampered request. But when that payload carried a link, all it could say was
"the QR carries a link" - the link itself was never looked at. This module
looks at it.

WHAT IT DOES NOT DO, AND WHY
----------------------------
It does not fetch the URL. Not laziness - fetching an attacker-controlled URL
from the payer's device or from the server is an own goal: it confirms the
address is live, leaks who is checking, follows redirects into whatever the
attacker wants loaded, and turns a fraud check into a request forgery. Every
signal here comes from the STRUCTURE of the address, which is exactly where
the deception lives.

There is no reputation feed either. A blocklist is only as fresh as its last
update, and scam domains are registered and burned within days. Structure
outlives the domain: a look-alike of a bank's name is a look-alike whether or
not anyone has reported it yet.

WHAT IT REUSES
--------------
The homoglyph folding written for UPI IDs works unchanged on hostnames -
the trick that turns okaxis into okaxls is the trick that turns
onlinesbi into 0nlinesbi. So canonical(), PROTECTED_NAMES, LURE_WORDS and the
edit distance all come from vpa.py rather than being written twice.

THE SIGNAL NOTHING ELSE HAS
---------------------------
A link claiming one brand, next to a payee address belonging to someone else,
is a contradiction no single-modality check can see. "Your SBI account is
blocked, verify at sbi-secure.top, pay rk4482@ybl" is three streams
disagreeing, and disagreement is the strongest evidence in the system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import unquote, urlsplit

from backend.app.services.vpa import (
    total_weight,
    LURE_WORDS,
    PROTECTED_NAMES,
    VpaFinding,
    _edit_distance,
    canonical,
)

# ── Reference data ────────────────────────────────────────────────────────────

# The registrable domains these brands actually use. A hostname that mentions
# the brand but does not end in one of these is claiming something untrue.
LEGITIMATE_DOMAINS: dict[str, tuple[str, ...]] = {
    "sbi": ("sbi.co.in", "onlinesbi.sbi", "onlinesbi.com", "yonosbi.com"),
    "hdfc": ("hdfcbank.com",),
    "icici": ("icicibank.com",),
    "axis": ("axisbank.com",),
    "kotak": ("kotak.com",),
    "pnb": ("pnbindia.in", "netpnb.com"),
    "canara": ("canarabank.com", "canarabank.in"),
    "rbi": ("rbi.org.in",),
    "npci": ("npci.org.in",),
    "upi": ("npci.org.in",),
    "bhim": ("bhimupi.org.in", "npci.org.in"),
    "paytm": ("paytm.com", "paytmbank.com"),
    "phonepe": ("phonepe.com",),
    "googlepay": ("pay.google.com", "google.com"),
    "gpay": ("pay.google.com", "google.com"),
    "amazon": ("amazon.in", "amazon.com"),
    "amazonpay": ("amazon.in", "amazon.com"),
    "flipkart": ("flipkart.com",),
    "irctc": ("irctc.co.in", "indianrail.gov.in"),
    "lic": ("licindia.in",),
    "epfo": ("epfindia.gov.in",),
    "incometax": ("incometax.gov.in", "incometaxindia.gov.in"),
    "gst": ("gst.gov.in",),
    "uidai": ("uidai.gov.in",),
    "aadhaar": ("uidai.gov.in",),
    "swiggy": ("swiggy.com",),
    "zomato": ("zomato.com",),
    "jio": ("jio.com", "jiofiber.com"),
    "airtel": ("airtel.in",),
    "zerodha": ("zerodha.com",),
    "groww": ("groww.in",),
    # Without these, the brand is recognised but has no reference domains, so
    # "unionbank-kyc-verify.xyz" scored 36 where "sbi-kyc-verify.xyz" scored
    # 71 - the same attack, graded differently by an accident of this table.
    "unionbank": ("unionbankofindia.co.in", "onlineunionbank.co.in"),
    "mobikwik": ("mobikwik.com",),
    "myntra": ("myntra.com",),
    "bigbasket": ("bigbasket.com",),
    "vodafone": ("myvi.in", "vodafone.in"),
    "netflix": ("netflix.com",),
    "upstox": ("upstox.com",),
    "pmkisan": ("pmkisan.gov.in",),
    "bhim": ("bhimupi.org.in", "npci.org.in"),
}

# PROTECTED_NAMES carries several spellings of the same bank (sbi/statebank,
# icici/icicibank). Without these aliases "www.icicibank.com" matched the brand
# "icicibank", found no reference domains for it, and the real bank site was
# reported as off-brand.
_ALIASES: dict[str, str] = {
    "statebank": "sbi", "hdfcbank": "hdfc", "icicibank": "icici",
    "axisbank": "axis", "bankofbaroda": "canara", "bob": "canara",
}
for _alias, _target in _ALIASES.items():
    LEGITIMATE_DOMAINS.setdefault(_alias, LEGITIMATE_DOMAINS.get(_target, ()))
LEGITIMATE_DOMAINS["bankofbaroda"] = ("bankofbaroda.in", "bankofbaroda.co.in")
LEGITIMATE_DOMAINS["bob"] = LEGITIMATE_DOMAINS["bankofbaroda"]

# Shorteners hide the destination. Legitimate senders use them constantly,
# which is exactly why this is evidence rather than proof.
SHORTENERS: frozenset[str] = frozenset({
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "cutt.ly", "rb.gy", "shorturl.at", "rebrand.ly", "tiny.cc", "bl.ink",
    "short.io", "t.ly", "linktr.ee", "wa.link",
})

# Cheap, high-abuse TLDs. Indian banks and government departments do not
# operate on these; scam infrastructure is registered on them daily.
SUSPICIOUS_TLDS: frozenset[str] = frozenset({
    "xyz", "top", "tk", "ml", "ga", "cf", "gq", "buzz", "click", "link",
    "work", "rest", "icu", "cyou", "sbs", "fit", "monster", "quest", "bar",
    "cam", "surf", "lol", "beauty", "makeup", "skin", "hair", "autos",
})

# Two-level public suffixes that matter in India, so co.in is not mistaken
# for the registrable domain.
_MULTI_SUFFIXES: frozenset[str] = frozenset({
    "co.in", "net.in", "org.in", "gen.in", "firm.in", "ind.in", "gov.in",
    "nic.in", "ac.in", "edu.in", "res.in", "co.uk", "org.uk", "com.au",
})

_TLD_RE = r"(?:com|in|org|net|co|gov|edu|io|me|info|biz|app|dev|xyz|top|tk|ml|ga|cf|gq|buzz|click|link|work|rest|icu|cyou|sbs|fit|site|online|store|shop|live|club|fun|cc|ly|gl|to|sbi|bank|uk|us|au|ru|cn)"

# A hostname must end in a plausible TLD. Without that constraint the bare-host
# alternative matched ordinary prose ("blocked.Verify") and any UPI ID with a
# dot in the local part ("priya.sharma@okaxis" -> "priya.sharma"), inventing a
# link finding on a completely normal payment.
#
# upi:// is deliberately NOT matched here: a deep link is upi_qr.py's job, and
# the greedy match swallowed the url= parameter it carries - the one link that
# most needed analysing.
_URL_RE = re.compile(
    rf"""(?xi)
    (?:
        (?:https?://)[^\s<>"']+                                  # explicit scheme
      | (?<![\w@.])www\.[^\s<>"']+                               # www.something
      | (?<![\w@.])
        (?:[a-z0-9](?:[a-z0-9\-]{{0,61}}[a-z0-9])?\.)+            # host.
        {_TLD_RE}\b(?:/[^\s<>"']*)?                              # tld[/path]
    )
    """
)

# Words that are domains in name only - avoid flagging file names and prose.
_NOT_A_HOST = re.compile(r"\.(?:jpg|jpeg|png|gif|pdf|docx?|xlsx?|txt|zip|mp4)$", re.I)

FEATURE_ORDER: tuple[str, ...] = (
    "ip_host",
    "punycode",
    "credentials_in_url",
    "app_download",
    "brand_typosquat",
    "brand_in_subdomain",
    "brand_not_on_own_domain",
    "shortener",
    "suspicious_tld",
    "lure_in_host",
    "no_https",
    "excessive_hyphens",
    "deep_subdomains",
)

SEVERITY: dict[str, str] = {
    "ip_host": "critical",
    "punycode": "critical",
    "credentials_in_url": "critical",
    "app_download": "critical",
    "brand_typosquat": "critical",
    "brand_in_subdomain": "high",
    "brand_not_on_own_domain": "high",
    "shortener": "high",
    "lure_in_host": "warn",
    "suspicious_tld": "warn",
    "no_https": "warn",
    "excessive_hyphens": "info",
    "deep_subdomains": "info",
}

MESSAGES: dict[str, str] = {
    "ip_host": "The link points at a bare IP address instead of a domain name. "
               "No bank or biller does this.",
    "punycode": "The address uses punycode (xn--), which renders as characters "
                "that look like ordinary letters. This is how a fake domain is "
                "made to display as the real one.",
    "credentials_in_url": "Everything before the @ in this link is ignored by the "
                          "browser. The real destination is what follows it.",
    "app_download": "The link downloads an app file directly rather than sending you "
                    "to a store. Installing it hands over your device.",
    "brand_typosquat": "The domain is one character away from a real one. It is a "
                       "look-alike, not the real site.",
    "brand_in_subdomain": "A brand name appears in the subdomain, but the domain that "
                          "actually owns this address is somebody else's.",
    "brand_not_on_own_domain": "The link mentions a brand but is not on any domain that "
                               "brand uses.",
    "shortener": "A shortened link hides where it actually goes. Expand it before you "
                 "trust it.",
    "lure_in_host": "The domain combines a brand name with a word like verify, refund or "
                    "kyc - the shape of a phishing address.",
    "suspicious_tld": "This kind of domain is cheap, disposable and heavily abused. "
                      "Banks and government departments do not use it.",
    "no_https": "The link is not encrypted, so anything entered on it travels in the "
                "clear.",
    "excessive_hyphens": "The domain is unusually hyphenated, a common way to pack a "
                         "brand name into an address that is not the brand's.",
    "deep_subdomains": "The address is buried under several subdomains, which pushes the "
                       "real domain out of sight on a phone.",
}


@dataclass
class LinkVerdict:
    url: str
    host: str
    registrable: str
    features: dict[str, int] = field(default_factory=dict)
    claimed_brand: Optional[str] = None
    findings: list[VpaFinding] = field(default_factory=list)

    @property
    def score(self) -> int:
        return total_weight(self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "host": self.host,
            "registrable": self.registrable,
            "claimed_brand": self.claimed_brand,
            "score": self.score,
            "features": self.features,
            "findings": [
                {"code": f.code, "severity": f.severity, "message": f.message}
                for f in self.findings
            ],
        }


@dataclass
class LinkAnalysis:
    found: int = 0
    links: list[LinkVerdict] = field(default_factory=list)

    @property
    def score(self) -> int:
        """The worst link decides. Two bad links are not twice as bad."""
        return max((link.score for link in self.links), default=0)

    @property
    def findings(self) -> list[VpaFinding]:
        out: list[VpaFinding] = []
        for link in self.links:
            out.extend(link.findings)
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "score": self.score,
            "links": [link.as_dict() for link in self.links],
        }


# ── Parsing ───────────────────────────────────────────────────────────────────

def extract_urls(text: Optional[str]) -> list[str]:
    """Every link-shaped run in the text, de-duplicated, order preserved."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.finditer(text):
        raw = match.group(0).rstrip(".,;:!?)\"'")
        if _NOT_A_HOST.search(raw):
            continue
        if raw.lower() in seen:
            continue
        seen.add(raw.lower())
        out.append(raw)
    return out


def _split(url: str) -> tuple[str, str, str, str]:
    """(scheme, authority, host, path) with a scheme filled in when missing."""
    candidate = url if "://" in url else f"http://{url}"
    parts = urlsplit(candidate)
    authority = parts.netloc
    host = authority.split("@")[-1].split(":")[0].lower()
    return parts.scheme.lower(), authority, host, unquote(parts.path or "")


def registrable_domain(host: str) -> str:
    """The part someone actually registered - co.in and gov.in are suffixes."""
    labels = host.split(".")
    if len(labels) < 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
# Sorted so the mapping is deterministic: PROTECTED_NAMES is a set, and the
# substring scan below used to return a different brand run to run.
_CANON_BRANDS = {canonical(name): name for name in sorted(PROTECTED_NAMES)}
# Separators a brand is glued to in a phishing host: sbi-verify, paytm_refund,
# icicikyc. Requiring one of these (or a whole label) stops a three-letter
# brand matching inside an unrelated word - "gstatic.com" is not "gst".
# The canonical first label of every domain each brand really uses, for the
# look-alike comparison.
_CANON_DOMAIN_LABELS: dict[str, tuple[str, ...]] = {
    brand: tuple(canonical(d.split(".", 1)[0]) for d in domains)
    for brand, domains in LEGITIMATE_DOMAINS.items()
}
_LURE_CANON = tuple(sorted({canonical(w) for w in LURE_WORDS if len(canonical(w)) >= 3}))


def _brand_claimed_by(host: str) -> Optional[str]:
    """Which protected brand this hostname is invoking, if any."""
    for label in host.split("."):
        folded = canonical(label)
        if folded in _CANON_BRANDS:
            return _CANON_BRANDS[folded]
    # A look-alike of a domain the brand really uses. canonical() folds the
    # homoglyphs, so "0nlinesbi" and "onlinesbi" compare equal here - the same
    # mechanism that catches okaxls for okaxis.
    for label in host.split("."):
        folded = canonical(label)
        if len(folded) < 4:
            continue
        for brand, domains in _CANON_DOMAIN_LABELS.items():
            if any(_edit_distance(folded, d) <= 1 for d in domains):
                return brand

    # A brand glued to a lure word is the phishing shape: sbi-verify,
    # paytm-refund, icici-kyc. A bare substring is not - "gstatic" contains
    # "gst" and "flipkartner" would contain "flipkart", and neither is a claim.
    for label in host.split("."):
        folded = canonical(label)
        for canon_brand, brand in _CANON_BRANDS.items():
            if len(canon_brand) < 3 or canon_brand not in folded:
                continue
            remainder = folded.replace(canon_brand, "", 1)
            if not remainder or any(lure in remainder for lure in _LURE_CANON):
                return brand
    return None


def _is_legitimate(brand: str, registrable: str) -> bool:
    """True when the domain is one the brand really uses.

    A brand with no reference domains here returns True - not because the link
    is safe, but because this check cannot speak to it. Saying "not on its own
    domain" about a brand whose domains we never recorded would be asserting
    something we do not know, and it would fire on every real site of every
    brand missing from the table.
    """
    known = LEGITIMATE_DOMAINS.get(brand)
    if not known:
        return True
    return registrable in known


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyse_url(url: str) -> LinkVerdict:
    scheme, authority, host, path = _split(url)
    registrable = registrable_domain(host)
    features = {code: 0 for code in FEATURE_ORDER}

    if _IPV4.match(host):
        features["ip_host"] = 1
    if "xn--" in host:
        features["punycode"] = 1
    if "@" in authority:
        features["credentials_in_url"] = 1
    if path.lower().endswith((".apk", ".exe", ".msi")):
        features["app_download"] = 1
    if host in SHORTENERS or registrable in SHORTENERS:
        features["shortener"] = 1
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld in SUSPICIOUS_TLDS:
        features["suspicious_tld"] = 1
    if scheme == "http":
        features["no_https"] = 1
    if registrable.count("-") >= 2:
        features["excessive_hyphens"] = 1
    if host.count(".") >= 4:
        features["deep_subdomains"] = 1

    brand = _brand_claimed_by(host)
    have_reference = bool(LEGITIMATE_DOMAINS.get(brand or ""))
    if brand and have_reference and not _is_legitimate(brand, registrable):
        canon_registrable = canonical(registrable.rsplit(".", 1)[0])
        real_domains = LEGITIMATE_DOMAINS.get(brand, ())

        # One character away from a domain the brand really uses.
        typosquat = any(
            _edit_distance(canon_registrable, canonical(real.rsplit(".", 1)[0])) <= 1
            for real in real_domains
        )
        brand_label_position = [
            i for i, label in enumerate(host.split(".")[:-2])
            if canonical(label) in _CANON_BRANDS
        ]

        if typosquat:
            features["brand_typosquat"] = 1
        elif brand_label_position:
            features["brand_in_subdomain"] = 1
        else:
            features["brand_not_on_own_domain"] = 1

    # Outside the reference-domain branch on purpose: "unionbank-kyc-verify.xyz"
    # is the same attack as "sbi-kyc-verify.xyz", and the only difference was
    # that one brand happened to be missing from LEGITIMATE_DOMAINS.
    if brand:
        folded_host = canonical(host)
        if any(canonical(word) in folded_host for word in LURE_WORDS):
            features["lure_in_host"] = 1

    findings = [
        VpaFinding(f"link_{code}", SEVERITY[code], MESSAGES[code])
        for code in FEATURE_ORDER
        if features[code]
    ]
    if brand and (features["brand_typosquat"] or features["brand_in_subdomain"]
                  or features["brand_not_on_own_domain"]):
        real = LEGITIMATE_DOMAINS.get(brand, ())
        if real:
            findings.append(VpaFinding(
                "link_brand_claim", "info",
                f"This link invokes {brand}, whose real address is {real[0]}. "
                f"The link is on {registrable}.",
            ))

    return LinkVerdict(
        url=url, host=host, registrable=registrable,
        features=features, claimed_brand=brand, findings=findings,
    )


def analyse_links(text: Optional[str]) -> LinkAnalysis:
    urls = extract_urls(text)
    return LinkAnalysis(found=len(urls), links=[analyse_url(u) for u in urls])


def brand_conflicts_with_payee(analysis: LinkAnalysis, payee_vpa: Optional[str]) -> Optional[VpaFinding]:
    """The cross-modal check: link claims one brand, money goes elsewhere.

    Neither half is conclusive alone. A link mentioning SBI is not fraud; an
    unfamiliar payee is not fraud. A message pointing at an SBI page while the
    money goes to an unrelated personal address is the contradiction that no
    single-modality check can see.
    """
    if not payee_vpa:
        return None

    # Only links that are IMPERSONATING a brand count. A link to the brand's
    # real site is just a link: people paste irctc.co.in while settling a
    # ticket split with a friend, and calling that a conflict fires on
    # completely ordinary behaviour. The signal is a fake brand page next to an
    # unrelated payee, not a brand name next to an unrelated payee.
    impersonating = (
        "brand_typosquat", "brand_in_subdomain", "brand_not_on_own_domain",
    )
    brands = {
        link.claimed_brand
        for link in analysis.links
        if link.claimed_brand and any(link.features.get(f) for f in impersonating)
    }
    if not brands:
        return None

    # Compare the LOCAL part only. "@oksbi" is the Google Pay handle held by
    # every SBI customer, so folding the whole address in made canonical()
    # contain "sbi" and cancelled the conflict for a large share of real
    # payees. The handle says which bank issued the address, not who is paid.
    local_part = canonical(payee_vpa.split("@", 1)[0])
    for brand in brands:
        if canonical(brand) in local_part:
            return None      # link and payee agree - no conflict

    named = ", ".join(sorted(brands))
    return VpaFinding(
        "link_payee_brand_conflict", "high",
        f"The link talks about {named}, but the money would go to {payee_vpa}, "
        f"which has nothing to do with {named}. Genuine {named} payments go to a "
        f"{named} address.",
    )
