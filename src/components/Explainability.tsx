import React, { useState } from "react";
import { Search, AlertTriangle, ShieldAlert, Cpu } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";

interface ShapFeature {
  name: string;
  value: number;
}

export default function Explainability() {
  const [txId, setTxId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [features, setFeatures] = useState<ShapFeature[]>([]);

  const handleExplain = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!txId.trim()) {
      setError("Please provide a valid Transaction ID");
      return;
    }

    setLoading(true);
    setError(null);
    setFeatures([]);

    try {
      const res = await fetch(`/api/explain/${txId.trim()}`);
      if (!res.ok) {
        throw new Error("Explainability index not found for this Transaction ID");
      }
      const data = await res.json();
      
      if (data.features && data.shap_values && data.shap_values[0]) {
        const mapped: ShapFeature[] = data.features.map((feat: string, index: number) => ({
          name: feat,
          value: parseFloat(data.shap_values[0][index]?.toFixed(4)) || 0,
        }));
        setFeatures(mapped);
      } else {
        throw new Error("No model explanation parameters found.");
      }
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in" id="shap-explainability-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Model Explainability (SHAP)</h1>
        <p className="text-slate-400">
          Decodes the underlying ensemble machine learning model weights, plotting SHAP values to explain individual UPI payment score allocations.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Input panel */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-fit">
          <h2 className="text-xl font-semibold text-white mb-4">Explain Prediction</h2>

          <form onSubmit={handleExplain} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Transaction ID</label>
              <input
                type="text"
                value={txId}
                onChange={(e) => setTxId(e.target.value)}
                placeholder="e.g. tx_e6c4ac"
                required
                className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg p-3 flex gap-2">
                <AlertTriangle className="h-5 w-5 shrink-0" />
                <span>{error}</span>
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
                  Explain Prediction
                </>
              )}
            </button>
          </form>

          <div className="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-500 space-y-2">
            <h4 className="font-semibold text-slate-400 uppercase">How to read:</h4>
            <p>
              Positive values (red) represent variables that contributed to accelerating/increasing the transaction's fraud risk score.
            </p>
            <p>
              Negative values (green) represent variables that stabilized/reduced the risk probability.
            </p>
          </div>
        </div>

        {/* Visualizer Panel */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-6">
          {features.length > 0 ? (
            <div className="space-y-6 animate-fade-in" id="shap-chart-container">
              <h3 className="text-lg font-semibold text-white">SHAP Waterfall Distribution</h3>

              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={features} layout="vertical" margin={{ left: 30, right: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" stroke="#94a3b8" fontSize={11} tickLine={false} />
                    <YAxis dataKey="name" type="category" stroke="#94a3b8" fontSize={11} tickLine={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px" }}
                      labelStyle={{ color: "#fff" }}
                    />
                    <Bar dataKey="value">
                      {features.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.value >= 0 ? "#f43f5e" : "#10b981"}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Auxiliary Summary */}
              <div className="bg-slate-950 rounded-xl p-4 border border-slate-900 flex items-start gap-3">
                <ShieldAlert className="h-5 w-5 text-indigo-400 mt-0.5 shrink-0" />
                <div>
                  <h4 className="text-xs font-semibold text-white uppercase">SHAP Attribution Inference</h4>
                  <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                    The leading feature impact is <strong className="text-slate-200">
                      {features.reduce((prev, curr) => Math.abs(curr.value) > Math.abs(prev.value) ? curr : prev).name}
                    </strong>. Model decision borders conform to behavioral bounds.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full min-h-[300px] flex flex-col items-center justify-center text-center p-12">
              <Cpu className="h-16 w-16 text-slate-800 mb-4" />
              <h3 className="text-lg font-semibold text-white mb-1">Enter Transaction ID</h3>
              <p className="text-slate-400 max-w-sm text-sm">
                Enter a transaction reference ID from the logs on the left panel to execute full model attribution explainer overlays.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
