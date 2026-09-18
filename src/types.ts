import type { RiskLevel, Verdict } from "./lib/verdict";

// `Verdict` is the canonical risk band and `RiskLevel` the legacy
// LOW / MEDIUM / HIGH label the older panels still render. Both come from
// lib/verdict so no view can spell a band its own way.

export interface Transaction {
  transaction_id: string;
  amount: number;
  device_score: number;
  location_score: number;
  velocity_score: number;
  sender: string;
  receiver: string;
  timestamp: string;
  // The canonical band for this row, decided by the server.
  verdict?: Verdict;
  // Legacy flag the monitor table renders. The server derives it from
  // `verdict`, so the two cannot disagree.
  risk: number;
  risk_score: number;
}

export interface BehaviorProfile {
  user_id: string;
  transaction_count: number;
  debit_count?: number;
  credit_count?: number;
  avg_amount: number;
  median_amount?: number;
  max_amount: number;
  min_amount: number;
  most_active_hour: number | null;
  night_transactions: number;
  /** Rows that carried a real clock time. The denominator for night_transactions. */
  timed_transaction_count?: number;
  /** Every distinct payee, not the top 10 merchant_frequency holds. */
  distinct_payees?: number;
  weekend_transactions: number;
  transactions_without_time?: number;
  favorite_merchants: string[];
  average_daily_transactions: number;
  failed_transactions: number;
  known_upi_ids: string[];
  merchant_frequency: Record<string, number>;
  hourly_distribution: Record<string, number>;
  monthly_totals: Record<string, number>;
  source_type: string;
  updated_at: string;
}

export interface PersonalizedAssessment {
  risk_score: number;
  // This family's own sub-score in the canonical vocabulary. It is not the
  // payment's verdict - that comes from the payee check, once every family has
  // been combined.
  band?: Verdict;
  // Legacy label, derived from `band` server-side.
  risk_level: RiskLevel;
  reasons: string[];
  comparison: {
    average_amount?: number;
    max_amount?: number;
    most_active_hour?: number | null;
    average_daily_transactions?: number;
    amount_multiple?: number;
    projected_daily_transactions?: number;
  };
  profile_available: boolean;
  timestamp: string;
  merchant: string;
  location: string | null;
}

export interface StatementTransactionsPage {
  total: number;
  limit: number;
  offset: number;
  truncated: boolean;
  transactions: StatementTransaction[];
}

export interface StatementTransaction {
  statement_id: string;
  user_id: string;
  timestamp: string;
  amount: number;
  merchant: string;
  upi_id?: string;
  status: string;
  reference_number?: string;
  source_type: string;
  raw_line: string;
  txn_type?: string;
  created_at: string;
}

export interface PayeeFinding {
  code: string;
  severity: "info" | "warn" | "high" | "critical";
  message: string;
}

export interface PayeeReputation {
  vpa: string;
  known: boolean;
  display_name: string | null;
  first_seen: string | null;
  last_seen: string | null;
  age_days: number | null;
  payment_count: number;
  distinct_payers: number;
  repeat_payers: number;
  total_amount: number;
  mean_amount: number | null;
  amount_spread: number | null;
  reports: number;
  blocked: boolean;
}

/** One evidence family's row, as the payee check publishes it. The payer's own
 *  assessment sits under `detail`; the family's contribution to the combined
 *  score is `score`, on a different scale, and the two are not interchangeable. */
export interface PayerBehaviourEvidence {
  available: boolean;
  score: number | null;
  severity: string | null;
  code: string;
  message?: string | null;
  facts?: string[];
  detail: PersonalizedAssessment | null;
}

export interface PayeeCheckResult {
  input: string;
  input_kind: string;
  payee: {
    vpa: string | null;
    key: string;
    display_name: string | null;
    valid: boolean;
    handle_type: string;
    impersonates: string | null;
  };
  request: {
    amount: number | null;
    amount_locked: boolean;
    note: string | null;
    merchant_code: string | null;
    signed: boolean;
  };
  reputation: PayeeReputation | null;
  risk_score: number;
  // The canonical classification. `decision` is the same value under the name
  // the first version of this screen read, and is kept only for that.
  verdict: Verdict;
  decision: Verdict;
  headline: string;
  component_scores: {
    address_and_qr: number;
    payee_history: number;
    amount_context: number;
    stated_intent: number;
    message_pressure: number;
    link_safety: number;
  };
  intent: {
    supplied: boolean;
    intent: string | null;
    label: string | null;
    score: number;
    findings: PayeeFinding[];
  };
  message_pressure: {
    supplied: boolean;
    score: number;
    probability: number;
    patterns: Record<string, number>;
    language_note: string | null;
    model: string;
    weak_only: boolean;
    findings: { code: string; severity: string; message: string; quote: string | null }[];
  };
  links: {
    found: number;
    score: number;
    links: {
      url: string;
      host: string;
      registrable: string;
      claimed_brand: string | null;
      score: number;
      features: Record<string, number>;
      findings: PayeeFinding[];
    }[];
  };
  // What corroborated, and who saw each thing. `facts` are the distinct
  // observations; `observed_by` maps each one to the families that reported it.
  // This used to be `{ families: string[] }` - the fact-aware corroboration
  // change renamed it server-side and this type was not updated, so the screen
  // read `agreement.families.length` off undefined and crashed on exactly the
  // payments that corroborate.
  agreement: {
    facts: string[];
    bonus: number;
    observed_by?: Record<string, string[]>;
  };
  findings: PayeeFinding[];
  payer_behaviour: PayerBehaviourEvidence | null;
}

export interface IntentOption {
  id: string;
  label: string;
}
