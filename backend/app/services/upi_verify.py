"""Checking that a UPI ID is real.

There are three different questions here and they are worth keeping apart,
because conflating them is how a system ends up claiming more than it knows:

  1. Is it well formed?          name@handle, valid characters.
  2. Is the handle a real PSP?   @okaxis exists, @okaxls does not.
  3. Does the account exist?     Only the payment network can answer this.

(1) and (2) are done locally by backend/app/services/vpa.py and cost nothing.
(3) requires a PSP or aggregator API - Razorpay, Cashfree and PayU all expose
VPA validation - which needs credentials this project does not ship with.

So (3) is a seam rather than a stub: configure a verifier and registration
enforces it; leave it unconfigured and the system says plainly that the
address is unverified rather than pretending it checked. Nothing anywhere
reports a UPI ID as verified unless a provider actually said so.

To turn it on, set in .env:

    UPI_VERIFY_URL=https://your-provider/validate/vpa
    UPI_VERIFY_KEY=...
    UPI_VERIFY_REQUIRED=true      # refuse registration if it cannot verify

The endpoint is expected to accept {"vpa": "..."} and answer
{"valid": true, "name": "ACCOUNT HOLDER"}. Adjust _parse_response for a
provider that words it differently.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from backend.app.core.config import get
from backend.app.services.vpa import analyse_vpa

TIMEOUT_SECONDS = 6


@dataclass
class VerificationResult:
    status: str          # "verified" | "not_found" | "malformed" | "unavailable"
    vpa: str
    name: Optional[str] = None
    detail: str = ""
    provider: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "verified"

    @property
    def checked_with_provider(self) -> bool:
        return self.provider is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "vpa": self.vpa,
            "name": self.name,
            "detail": self.detail,
            "provider": self.provider,
            "verified_by_provider": self.checked_with_provider and self.ok,
        }


def is_configured() -> bool:
    return bool(get("UPI_VERIFY_URL", ""))


def verification_required() -> bool:
    """Whether an unverifiable address should be refused at registration."""
    return get("UPI_VERIFY_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}


def _parse_response(payload: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Providers disagree on wording; accept the common shapes."""
    valid = payload.get("valid")
    if valid is None:
        valid = payload.get("success")
    if valid is None:
        status = str(payload.get("status", "")).lower()
        valid = status in {"valid", "success", "verified"} if status else None

    name = (
        payload.get("name")
        or payload.get("customer_name")
        or payload.get("account_holder")
        or (payload.get("data") or {}).get("name")
        if isinstance(payload.get("data"), dict) or "name" in payload
        else None
    )
    return bool(valid), name


def _call_provider(url: str, key: str, vpa: str) -> dict[str, Any]:
    """The one network call, kept separate so it can be substituted in tests."""
    request = urllib.request.Request(
        url,
        data=json.dumps({"vpa": vpa}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {key}"} if key else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read())
    return payload if isinstance(payload, dict) else {}


def verify_vpa(vpa: str) -> VerificationResult:
    """Local checks always; a provider call only when one is configured."""
    analysis = analyse_vpa(vpa)
    normalised = analysis.normalised

    if not analysis.valid:
        return VerificationResult(
            "malformed", normalised,
            detail="That is not a valid UPI ID. It should look like name@bank.",
        )
    if not analysis.handle_known:
        return VerificationResult(
            "malformed", normalised,
            detail=f"@{analysis.handle} is not a handle any known UPI provider uses. "
                   f"Check the spelling.",
        )

    url = get("UPI_VERIFY_URL", "")
    if not url:
        return VerificationResult(
            "unavailable", normalised,
            detail="Format and provider handle look right. The account itself was "
                   "not checked: no verification provider is configured.",
        )

    key = get("UPI_VERIFY_KEY", "")
    try:
        payload = _call_provider(url, key, normalised)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # A provider being down must not read as "this address is fake".
        return VerificationResult(
            "unavailable", normalised, provider=None,
            detail=f"Could not reach the verification provider ({exc}). The address "
                   f"was not checked against the payment network.",
        )

    valid, name = _parse_response(payload)
    provider = get("UPI_VERIFY_PROVIDER", "configured provider")
    if valid:
        return VerificationResult(
            "verified", normalised, name=name, provider=provider,
            detail=f"Confirmed by {provider}" + (f" as {name}" if name else ""),
        )
    return VerificationResult(
        "not_found", normalised, provider=provider,
        detail=f"{provider} does not recognise this UPI ID.",
    )
