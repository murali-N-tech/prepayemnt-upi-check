import React, { useState } from "react";
import { Search, AlertTriangle, ShieldCheck, HelpCircle, MapPin, Landmark } from "lucide-react";
import { PersonalizedAssessment } from "../types";
import { useAuth } from "../context/AuthContext";

export default function PrePaymentRiskCheck() {
  const { api, username } = useAuth();
  const [merchant, setMerchant] = useState("");
  const [amount, setAmount] = useState("");
  const [upiId, setUpiId] = useState("");
  const [location, setLocation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<PersonalizedAssessment | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!merchant.trim() || !amount) {
      setError("Please fill out all required fields (Merchant, Amount).");
      return;
    }

    setLoading(true);
    setError(null);
    setAssessment(null);

    const payload = {
      amount: parseFloat(amount),
      merchant: merchant.trim(),
      timestamp: new Date().toISOString(),
      upi_id: upiId.trim() || undefined,
      location: location.trim() || undefined,
    };

    try {
      const data = await api<PersonalizedAssessment>("/api/personalized-risk-check", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAssessment(data);
    } catch (err: any) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in" id="personalized-risk-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">Personalized Pre-Payment Risk</h1>
        <p className="text-ink-muted">
          Evaluates transactions before payment execution by cross-referencing user behavioral historical models extracted from statements.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Check Form */}
        <div className="bg-surface border border-line rounded-xl p-6 h-fit" id="check-form-card">
          <h2 className="text-xl font-semibold text-ink mb-4">Run Risk Check</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-ink-muted mb-1">Merchant / Recipient *</label>
              <input
                type="text"
                value={merchant}
                onChange={(e) => setMerchant(e.target.value)}
                placeholder="e.g. Amazon Pay"
                required
                className="w-full px-4 py-2 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-ink-muted mb-1">Amount (INR) *</label>
              <input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="₹ Amount"
                required
                className="w-full px-4 py-2 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-ink-muted mb-1">UPI ID (Optional)</label>
              <input
                type="text"
                value={upiId}
                onChange={(e) => setUpiId(e.target.value)}
                placeholder="e.g. merchant@paytm"
                className="w-full px-4 py-2 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-ink-muted mb-1">Location (Optional)</label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. Mumbai, Maharashtra (recorded, not scored)"
                className="w-full px-4 py-2 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-danger text-sm rounded-lg p-3">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 text-white font-medium rounded-lg shadow-sm transition flex items-center justify-center gap-2"
            >
              {loading ? (
                <div className="h-5 w-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <>
                  <Search className="h-4 w-4" />
                  Run Personalized Check
                </>
              )}
            </button>
          </form>
        </div>

        {/* Evaluation Output */}
        <div className="lg:col-span-2 space-y-6">
          {assessment ? (
            <div className="space-y-6 animate-fade-in" id="assessment-result">
              {/* Risk Score Summary Banner */}
              <div
                className={`border rounded-xl p-6 flex flex-col md:flex-row md:items-center justify-between gap-6 ${
                  assessment.risk_level === "HIGH"
                    ? "bg-rose-500/10 border-rose-500/20 text-danger"
                    : assessment.risk_level === "MEDIUM"
                    ? "bg-amber-500/10 border-amber-500/20 text-warn"
                    : "bg-emerald-500/10 border-emerald-500/20 text-ok"
                }`}
              >
                <div className="flex items-start gap-4">
                  {assessment.risk_level === "HIGH" || assessment.risk_level === "MEDIUM" ? (
                    <AlertTriangle className="h-12 w-12 shrink-0 mt-1" />
                  ) : (
                    <ShieldCheck className="h-12 w-12 shrink-0 mt-1" />
                  )}
                  <div>
                    <h3 className="text-xl font-bold text-ink">Assessment: {assessment.risk_level} RISK</h3>
                    <p className="text-ink-muted text-sm mt-1">
                      {assessment.profile_available 
                        ? `Payment behaviour matched with your profile (${username}).`
                        : "Compiled without baseline. Assessment is a general risk model."}
                    </p>
                  </div>
                </div>

                <div className="text-center shrink-0">
                  <div className="text-xs text-ink-muted uppercase font-semibold">UPI Risk Score</div>
                  <div className="text-5xl font-black text-ink mt-1">{assessment.risk_score}</div>
                  <div className="text-xs text-ink-muted mt-1">out of 100</div>
                </div>
              </div>

              {/* Reasons Breakdown */}
              <div className="bg-surface border border-line rounded-xl p-6">
                <h3 className="text-lg font-semibold text-ink mb-4 flex items-center gap-2">
                  <HelpCircle className="h-5 w-5 text-brand" />
                  Evaluation Reasons
                </h3>
                <ul className="space-y-3">
                  {assessment.reasons.map((reason, index) => (
                    <li key={index} className="flex gap-3 text-sm text-ink-muted bg-inset p-3 rounded-lg border border-line">
                      <span className="text-brand font-semibold">{index + 1}.</span>
                      <span>{reason}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Historical Comparison */}
              {assessment.profile_available && (
                <div className="bg-surface border border-line rounded-xl p-6">
                  <h3 className="text-lg font-semibold text-ink mb-4 flex items-center gap-2">
                    <Landmark className="h-5 w-5 text-brand" />
                    Comparison with Behavior Profile
                  </h3>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-4">
                      <div className="flex justify-between items-center pb-2 border-b border-line text-sm">
                        <span className="text-ink-muted">Average Transaction size</span>
                        <span className="font-semibold text-ink">₹{assessment.comparison.average_amount}</span>
                      </div>
                      <div className="flex justify-between items-center pb-2 border-b border-line text-sm">
                        <span className="text-ink-muted">Maximum Single size</span>
                        <span className="font-semibold text-ink">₹{assessment.comparison.max_amount}</span>
                      </div>
                      <div className="flex justify-between items-center pb-2 border-b border-line text-sm">
                        <span className="text-ink-muted">Most active Hour</span>
                        <span className="font-semibold text-ink">
                          {assessment.comparison.most_active_hour !== null ? `${assessment.comparison.most_active_hour}:00` : "-"}
                        </span>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <div className="flex justify-between items-center pb-2 border-b border-line text-sm">
                        <span className="text-ink-muted">Daily average Transactions</span>
                        <span className="font-semibold text-ink">{assessment.comparison.average_daily_transactions}</span>
                      </div>
                      <div className="flex justify-between items-center pb-2 border-b border-line text-sm">
                        <span className="text-ink-muted">Amount multiple of average</span>
                        <span className="font-semibold text-brand">
                          {assessment.comparison.amount_multiple !== undefined ? `${assessment.comparison.amount_multiple}x` : "-"}
                        </span>
                      </div>
                      <div className="flex justify-between items-center pb-2 border-b border-line text-sm">
                        <span className="text-ink-muted">Same-Day Projected Velocity</span>
                        <span className="font-semibold text-ink">{assessment.comparison.projected_daily_transactions} txs</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Geographic Parameters */}
              <div className="bg-surface border border-line rounded-xl p-6 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <MapPin className="h-5 w-5 text-brand" />
                  <div>
                    <span className="text-ink-muted text-xs block uppercase">Target Location</span>
                    <span className="text-sm font-semibold text-ink">{assessment.location || "Not Provided"}</span>
                  </div>
                </div>
                <div className="text-xs text-ink-subtle font-mono">
                  Recorded only &mdash; not used in scoring yet
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-surface/40 border border-line rounded-xl p-12 text-center h-full flex flex-col justify-center items-center">
              <ShieldCheck className="h-16 w-16 text-ink-faint mb-4" />
              <h3 className="text-lg font-semibold text-ink mb-1">Ready for Risk Inspection</h3>
              <p className="text-ink-muted max-w-md text-sm">
                Provide the transaction metrics in the left panel and click 'Run Personalized Check' to execute behavioral security analytics.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
