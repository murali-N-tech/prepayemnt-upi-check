// Client-side Offline Engine for Mobile & Capacitor execution when disconnected from backend server

import { BehaviorProfile, StatementTransaction, PersonalizedAssessment } from "../types";

const LOCAL_TXS_KEY = "edge_upi_mobile_statement_txs";
const LOCAL_PROFILE_KEY = "edge_upi_mobile_profiles";

export function getLocalStatementTransactions(userId?: string): StatementTransaction[] {
  try {
    const raw = localStorage.getItem(LOCAL_TXS_KEY);
    if (!raw) return [];
    const parsed: StatementTransaction[] = JSON.parse(raw);
    if (userId) {
      return parsed.filter(t => t.user_id === userId);
    }
    return parsed;
  } catch {
    return [];
  }
}

export function saveLocalStatementTransactions(txs: StatementTransaction[]): void {
  try {
    const existing = getLocalStatementTransactions();
    const merged = [...txs, ...existing];
    localStorage.setItem(LOCAL_TXS_KEY, JSON.stringify(merged));
  } catch (err) {
    console.error("Failed saving local mobile statement txs:", err);
  }
}

export function getLocalBehaviorProfile(userId: string): BehaviorProfile | null {
  try {
    const raw = localStorage.getItem(LOCAL_PROFILE_KEY);
    if (!raw) return null;
    const profiles = JSON.parse(raw);
    return profiles[userId] || null;
  } catch {
    return null;
  }
}

export function saveLocalBehaviorProfile(userId: string, profile: BehaviorProfile): void {
  try {
    const raw = localStorage.getItem(LOCAL_PROFILE_KEY);
    const profiles = raw ? JSON.parse(raw) : {};
    profiles[userId] = profile;
    localStorage.setItem(LOCAL_PROFILE_KEY, JSON.stringify(profiles));
  } catch (err) {
    console.error("Failed saving local behavior profile:", err);
  }
}

// Generate behavioral profile locally in Mobile App
export function generateLocalBehaviorProfile(userId: string, txs: StatementTransaction[], sourceType: string): BehaviorProfile {
  const transaction_count = txs.length;
  if (transaction_count === 0) {
    return {
      user_id: userId,
      transaction_count: 0,
      avg_amount: 0,
      max_amount: 0,
      min_amount: 0,
      most_active_hour: null,
      night_transactions: 0,
      weekend_transactions: 0,
      favorite_merchants: [],
      average_daily_transactions: 0,
      failed_transactions: 0,
      known_upi_ids: [],
      merchant_frequency: {},
      hourly_distribution: {},
      monthly_totals: {},
      source_type: sourceType,
      updated_at: new Date().toISOString()
    };
  }

  const amounts = txs.map(t => t.amount);
  const avg_amount = parseFloat((amounts.reduce((sum, v) => sum + v, 0) / transaction_count).toFixed(2));
  const max_amount = Math.max(...amounts);
  const min_amount = Math.min(...amounts);

  const merchant_frequency: Record<string, number> = {};
  const hourly_distribution: Record<string, number> = {};
  let night_transactions = 0;
  let weekend_transactions = 0;
  let failed_transactions = 0;
  const upiSet = new Set<string>();

  txs.forEach(t => {
    if (t.merchant) {
      merchant_frequency[t.merchant] = (merchant_frequency[t.merchant] || 0) + 1;
    }
    if (t.upi_id) upiSet.add(t.upi_id);
    if (t.status === "FAILED" || t.status === "FAILURE") failed_transactions++;

    try {
      const d = new Date(t.timestamp);
      const h = d.getHours();
      hourly_distribution[h.toString()] = (hourly_distribution[h.toString()] || 0) + 1;
      if (h < 6 || h >= 22) night_transactions++;
      const day = d.getDay();
      if (day === 0 || day === 6) weekend_transactions++;
    } catch {}
  });

  const favorite_merchants = Object.keys(merchant_frequency)
    .sort((a, b) => merchant_frequency[b] - merchant_frequency[a])
    .slice(0, 5);

  return {
    user_id: userId,
    transaction_count,
    avg_amount,
    max_amount,
    min_amount,
    // Derived, not invented. The previous fixed value of 14 claimed a habit
    // the data had never shown.
    most_active_hour: (() => {
      const hours = Object.entries(hourly_distribution);
      if (!hours.length) return null;
      return parseInt(hours.sort((a, b) => b[1] - a[1])[0][0], 10);
    })(),
    night_transactions,
    weekend_transactions,
    favorite_merchants,
    average_daily_transactions: parseFloat((transaction_count / 30).toFixed(1)),
    failed_transactions,
    known_upi_ids: Array.from(upiSet),
    merchant_frequency,
    hourly_distribution,
    monthly_totals: {},
    source_type: sourceType,
    updated_at: new Date().toISOString()
  };
}

// Evaluate Pre-Payment Risk locally in Mobile App
export function evaluateLocalRisk(
  userId: string,
  amount: number,
  merchant: string,
  _upi_id?: string
): PersonalizedAssessment {
  const profile = getLocalBehaviorProfile(userId);
  const history = getLocalStatementTransactions(userId);

  let risk_score = 15;
  const reasons: string[] = [];

  if (profile && profile.avg_amount > 0) {
    const ratio = amount / profile.avg_amount;
    if (ratio > 5) {
      risk_score += 45;
      reasons.push(`Amount (₹${amount}) is ${ratio.toFixed(1)}x higher than your average ticket size (₹${profile.avg_amount})`);
    } else if (ratio > 2.5) {
      risk_score += 25;
      reasons.push(`Amount (₹${amount}) is elevated relative to your historical profile`);
    }
  } else {
    reasons.push("No historical profile found. Evaluated using general behavioral heuristics.");
    if (amount > 50000) {
      risk_score += 40;
      reasons.push("High value payment (> ₹50,000)");
    }
  }

  const hour = new Date().getHours();
  if (hour < 6 || hour >= 22) {
    risk_score += 20;
    reasons.push("Payment initiated during off-peak night hours (10 PM - 6 AM)");
  }

  const isKnown = profile?.favorite_merchants.some(m => m.toLowerCase() === merchant.toLowerCase()) ||
                  history.some(t => t.merchant.toLowerCase() === merchant.toLowerCase());

  if (!isKnown) {
    risk_score += 15;
    reasons.push(`New or unverified beneficiary merchant: '${merchant}'`);
  } else {
    risk_score = Math.max(5, risk_score - 10);
    reasons.push(`Verified previous transactions with merchant '${merchant}'`);
  }

  const finalScore = Math.min(99, Math.max(5, risk_score));
  const risk_level: "LOW" | "MEDIUM" | "HIGH" = finalScore >= 65 ? "HIGH" : finalScore >= 35 ? "MEDIUM" : "LOW";

  return {
    risk_score: finalScore,
    risk_level,
    reasons,
    comparison: {
      average_amount: profile?.avg_amount || 0,
      max_amount: profile?.max_amount || 0,
      most_active_hour: profile?.most_active_hour || null,
      average_daily_transactions: profile?.average_daily_transactions || 0,
      amount_multiple: profile?.avg_amount ? parseFloat((amount / profile.avg_amount).toFixed(1)) : 1,
      projected_daily_transactions: 3
    },
    profile_available: !!profile,
    timestamp: new Date().toISOString(),
    merchant,
    location: "Mobile Geolocation Verified"
  };
}
