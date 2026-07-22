import React, { useState } from "react";
import { AlertTriangle, ShieldCheck, Cpu, Sliders } from "lucide-react";

export default function FraudDetection() {
  const [userId, setUserId] = useState("");
  const [merchant, setMerchant] = useState("");
  const [amount, setAmount] = useState("");
  const [deviceScore, setDeviceScore] = useState(0.5);
  const [locationScore, setLocationScore] = useState(0.5);
  const [velocityScore, setVelocityScore] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any | null>(null);

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId.trim() || !merchant.trim() || !amount) {
      setError("Please fill out User ID, Merchant and Amount.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    const payload = {
      amount: parseFloat(amount),
      device_score: deviceScore,
      location_score: locationScore,
      velocity_score: velocityScore,
      sender: userId.trim(),
      receiver: merchant.trim(),
      timestamp: new Date().toISOString(),
    };

    try {
      const res = await fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw new Error("Failed to process transaction. Check server status.");
      }

      const data = await res.json();
      setResult(data);
    } catch (err: any) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in" id="fraud-detection-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Transaction Risk Analysis</h1>
        <p className="text-slate-400">
          Run high-velocity machine learning transaction scoring models combined with behavioral heuristic rules.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Input Parameters Form */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-fit" id="risk-analysis-form">
          <h2 className="text-xl font-semibold text-white mb-4">Analyze Transaction</h2>

          <form onSubmit={handleAnalyze} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">User ID</label>
              <input
                type="text"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder="e.g. user_1"
                required
                className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Merchant / Payee</label>
              <input
                type="text"
                value={merchant}
                onChange={(e) => setMerchant(e.target.value)}
                placeholder="e.g. Swiggy"
                required
                className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Amount (INR)</label>
              <input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="₹ Amount"
                required
                className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {/* Sliders for advanced biometric metrics */}
            <div className="pt-4 border-t border-slate-800 space-y-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <Sliders className="h-3.5 w-3.5" /> Biometrics & Device Scores
              </h3>

              <div>
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Device Trust Score</span>
                  <span className="text-white font-semibold">{deviceScore.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={deviceScore}
                  onChange={(e) => setDeviceScore(parseFloat(e.target.value))}
                  className="w-full accent-indigo-500"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Geographic Location Score</span>
                  <span className="text-white font-semibold">{locationScore.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={locationScore}
                  onChange={(e) => setLocationScore(parseFloat(e.target.value))}
                  className="w-full accent-indigo-500"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Velocity count (Same Hour)</span>
                  <span className="text-white font-semibold">{velocityScore} txs</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="15"
                  step="1"
                  value={velocityScore}
                  onChange={(e) => setVelocityScore(parseInt(e.target.value))}
                  className="w-full accent-indigo-500"
                />
              </div>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg p-3">
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
                  <Cpu className="h-4 w-4" />
                  Analyze Transaction
                </>
              )}
            </button>
          </form>
        </div>

        {/* Results Panel */}
        <div className="lg:col-span-2 space-y-6">
          {result ? (
            <div className="space-y-6 animate-fade-in" id="analysis-result">
              {/* Core Risk Metrics */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-center">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">Risk Score</span>
                  <span className="text-6xl font-black text-white block mt-2">{result.risk_score}</span>
                  <span className="text-xs text-slate-500 block mt-2">out of 100</span>
                </div>

                <div className={`border rounded-xl p-6 flex flex-col justify-center items-center ${
                  result.risk === 1
                    ? "bg-rose-500/10 border-rose-500/20 text-rose-400"
                    : "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                }`}>
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">Decision Result</span>
                  <span className="text-3xl font-extrabold text-white block mt-2">
                    {result.risk === 1 ? "BLOCKED / FRAUD" : "APPROVED"}
                  </span>
                  <span className="text-xs text-slate-300 text-center block mt-2 max-w-xs">
                    {result.risk === 1 
                      ? "Transaction flagged as HIGH probability of malicious behaviour." 
                      : "Transaction conforms to standard UPI security guidelines."}
                  </span>
                </div>
              </div>

              {/* Transaction Receipt Details */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-sm text-slate-300">
                <h3 className="font-semibold text-white mb-3">Transaction Details</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs">
                  <div>
                    <span className="text-slate-500 block">TRANSACTION ID</span>
                    <span className="text-white font-semibold">{result.transaction_id}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">SENDER</span>
                    <span className="text-white font-semibold">{userId}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">RECEIVER</span>
                    <span className="text-white font-semibold">{merchant}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">AMOUNT (INR)</span>
                    <span className="text-white font-semibold">₹{amount}</span>
                  </div>
                </div>
              </div>

              {/* Personalized Assessment Result */}
              {result.personalized_assessment ? (
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
                  <h3 className="text-lg font-bold text-white flex items-center gap-2 border-b border-slate-800 pb-3">
                    <ShieldCheck className="h-5 w-5 text-indigo-400" />
                    Personalized Behaviour Assessment
                  </h3>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="p-4 bg-slate-950 rounded-lg">
                      <span className="text-xs text-slate-500 block">Behavior Score</span>
                      <span className="text-2xl font-bold text-white mt-1">{result.personalized_assessment.risk_score}</span>
                    </div>

                    <div className="p-4 bg-slate-950 rounded-lg">
                      <span className="text-xs text-slate-500 block">Behavior Level</span>
                      <span className={`text-2xl font-bold mt-1 ${
                        result.personalized_assessment.risk_level === "HIGH" ? "text-rose-400" : "text-emerald-400"
                      }`}>{result.personalized_assessment.risk_level}</span>
                    </div>
                  </div>

                  <div>
                    <span className="text-xs font-semibold text-slate-400 block mb-2">Behavior Anomalies</span>
                    <ul className="space-y-2">
                      {result.personalized_assessment.reasons.map((r: string, idx: number) => (
                        <li key={idx} className="text-sm text-slate-300 bg-slate-950/50 p-2.5 rounded border border-slate-900/50">
                          • {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-5 text-center">
                  <span className="text-xs text-slate-400 block mb-1">Personalized Behavioral Check Not Executed</span>
                  <p className="text-xs text-slate-500 max-w-md mx-auto">
                    To activate personalized checks, upload a behavior statement in the **Statement Profiling** tab for user "{userId}".
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-12 text-center h-full flex flex-col justify-center items-center">
              <Cpu className="h-16 w-16 text-slate-700 mb-4" />
              <h3 className="text-lg font-semibold text-white mb-1">Risk Predictor</h3>
              <p className="text-slate-400 max-w-md text-sm">
                Submit a UPI transaction to feed the real-time scoring model and check risk probabilities.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
