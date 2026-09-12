/**
 * What a UPI payment is allowed to be, on the client.
 *
 * Mirrors backend/app/core/upi_limits.py. The backend is the authority — it
 * returns 422 for an impossible amount — but an amount field with no `max`
 * let people type ₹1 crore, wait for a round trip, and get a validation error
 * for something the field should never have accepted.
 *
 * NPCI per-transaction caps, in force since 15 September 2025:
 *   P2P and standard merchant payments   ₹1,00,000
 *   Verified merchants in certain
 *   categories (insurance, capital
 *   markets, travel, education,
 *   healthcare, collections, credit
 *   card bills, tax, GeM)                ₹5,00,000
 *
 * The client only ever assumes the standard cap. Whether a payee qualifies for
 * the higher one depends on a merchant code and signature in the QR, which the
 * backend checks — so the client never raises its own ceiling.
 */

export const UPI_PER_TXN_CAP = 100_000;
export const UPI_MERCHANT_CAP = 500_000;

/** Indian numbering, for a cap in a sentence: 100000 -> "₹1 lakh". */
export function describeCap(cap: number = UPI_PER_TXN_CAP): string {
  if (cap >= 100_000 && cap % 100_000 === 0) {
    return `₹${cap / 100_000} lakh`;
  }
  return `₹${cap.toLocaleString("en-IN")}`;
}

/**
 * null if this amount could be a real UPI payment, otherwise why not.
 * An empty string is "not typed yet", which is not an error.
 */
export function amountProblem(
  raw: string | number | null | undefined,
  cap: number = UPI_PER_TXN_CAP
): string | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value)) return "Enter an amount in rupees.";
  if (value < 0) return "An amount cannot be negative.";
  if (value === 0) return null; // not filled in yet
  if (value > cap) {
    return (
      `UPI does not carry more than ${describeCap(cap)} in one payment, so ` +
      `₹${value.toLocaleString("en-IN")} cannot be a UPI transaction.`
    );
  }
  return null;
}

/** Props every rupee input in this app should spread onto its <input>. */
export const rupeeInputProps = {
  type: "number" as const,
  min: "0",
  max: String(UPI_PER_TXN_CAP),
  step: "0.01",
  inputMode: "decimal" as const,
};
