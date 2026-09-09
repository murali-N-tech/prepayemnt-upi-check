import React, { useEffect, useState } from "react";

export interface UpiStatus {
  provider_configured: boolean;
  verification_required: boolean;
  checks: string[];
}

/** Reads what the server can actually check about a UPI ID.
 *
 * The point of showing this is honesty: without a provider configured the
 * system only knows the address is well formed and the handle is a real PSP,
 * and the sign-up screen should say that rather than implying the account was
 * confirmed to exist.
 */
export function useUpiStatus(): UpiStatus | null {
  const [status, setStatus] = useState<UpiStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/upi-status")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data) setStatus(data);
      })
      .catch(() => {
        // Status is informational; the form still works without it.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}

export const UpiStatusNote: React.FC<{ status: UpiStatus | null }> = ({ status }) => {
  if (!status) return null;

  return (
    <p className="mt-2 text-xs text-ink-muted">
      {status.provider_configured
        ? "Your UPI ID is checked against the payment network before the account is created."
        : "We check the format and the bank handle. The account itself is not verified against the payment network — no verification provider is configured."}
    </p>
  );
};
