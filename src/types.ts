export interface Transaction {
  transaction_id: string;
  amount: number;
  device_score: number;
  location_score: number;
  velocity_score: number;
  sender: string;
  receiver: string;
  timestamp: string;
  risk: number;
  risk_score: number;
}

export interface BehaviorProfile {
  user_id: string;
  transaction_count: number;
  avg_amount: number;
  max_amount: number;
  min_amount: number;
  most_active_hour: number | null;
  night_transactions: number;
  weekend_transactions: number;
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
  risk_level: "LOW" | "MEDIUM" | "HIGH";
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
  created_at: string;
}
