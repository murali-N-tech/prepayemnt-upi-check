/**
 * The risk-band vocabulary, mirrored for the offline mobile path.
 *
 * backend/app/core/verdict.py is the source of truth. Everything that reaches
 * a screen from the server carries the band the server decided; nothing in the
 * UI recomputes it. This file exists for one case only: the Capacitor build
 * evaluates a payment with no server to ask (services/mobileBackendAdapter),
 * and a payment it cannot classify is worse than one classified by a mirror.
 *
 * The mirror was not the problem. The problem was that the adapter had its own
 * ladder at 65 and 35, so the same score came out HIGH offline and MEDIUM
 * online - one number, two answers, depending on whether the phone had signal.
 * The thresholds below are the server's, and tests/test_verdict_vocabulary.py
 * reads this file and fails if they ever drift from the Python constants.
 */

export const BLOCK_AT = 70;
export const STEP_UP_AT = 45;
export const WARN_AT = 22;

export type Verdict = "APPROVE" | "WARN" | "STEP_UP" | "BLOCK";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

/** In order of severity. */
export const VERDICTS: readonly Verdict[] = ["APPROVE", "WARN", "STEP_UP", "BLOCK"];

export function verdictFromScore(score: number): Verdict {
  if (score >= BLOCK_AT) return "BLOCK";
  if (score >= STEP_UP_AT) return "STEP_UP";
  if (score >= WARN_AT) return "WARN";
  return "APPROVE";
}

const LEVEL_FOR: Record<Verdict, RiskLevel> = {
  BLOCK: "HIGH",
  STEP_UP: "MEDIUM",
  WARN: "LOW",
  APPROVE: "LOW",
};

/** The legacy LOW / MEDIUM / HIGH label, as a function of the band. */
export function levelFromVerdict(verdict: Verdict): RiskLevel {
  return LEVEL_FOR[verdict];
}

export function levelFromScore(score: number): RiskLevel {
  return levelFromVerdict(verdictFromScore(score));
}
