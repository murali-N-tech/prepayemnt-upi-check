import React, { useState } from "react";
import { AlertTriangle, ShieldAlert, Cpu } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { useAuth } from "../context/AuthContext";
import { tooltipProps, useChartTheme } from "../lib/chartTheme";

interface ShapFeature {
  name: string;
  value: number;
}

export default function Explainability() {
  const chart = useChartTheme();
  const { api } = useAuth();
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
      const data = await api<{ features?: string[]; shap_values?: number[][] }>(
        `/api/explain/${encodeURIComponent(txId.trim())}`
      );
      
      const shapRow = data.shap_values?.[0];
      if (data.features && shapRow) {
        const mapped: ShapFeature[] = data.features.map((feat: string, index: number) => ({
          name: feat,
          value: parseFloat(shapRow[index]?.toFixed(4) ?? "0") || 0,
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
        <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">Model Explainability (SHAP)</h1>
        <p className="text-ink-muted">
          Decodes the underlying ensemble machine learning model weights, plotting SHAP values to explain individual UPI payment score allocations.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Input panel */}
        <div className="bg-surface border border-line rounded-xl p-6 h-fit">
          <h2 className="text-xl font-semibold text-ink mb-4">Explain Prediction</h2>

          <form onSubmit={handleExplain} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-ink-muted mb-1">Transaction ID</label>
              <input
                type="text"
                value={txId}
                onChange={(e) => setTxId(e.target.value)}
                placeholder="e.g. tx_e6c4ac"
                required
                className="w-full px-4 py-2 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-danger text-sm rounded-lg p-3 flex gap-2">
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

          <div className="mt-6 pt-4 border-t border-line text-xs text-ink-subtle space-y-2">
            <h4 className="font-semibold text-ink-muted uppercase">How to read:</h4>
            <p>
              Positive values (red) represent variables that contributed to accelerating/increasing the transaction's fraud risk score.
            </p>
            <p>
              Negative values (green) represent variables that stabilized/reduced the risk probability.
            </p>
          </div>
        </div>

        {/* Visualizer Panel */}
        <div className="lg:col-span-2 bg-surface border border-line rounded-xl p-6">
          {features.length > 0 ? (
            <div className="space-y-6 animate-fade-in" id="shap-chart-container">
              <h3 className="text-lg font-semibold text-ink">SHAP Waterfall Distribution</h3>

              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={features} layout="vertical" margin={{ left: 30, right: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                    <XAxis type="number" stroke={chart.axis} fontSize={11} tickLine={false} />
                    <YAxis dataKey="name" type="category" stroke={chart.axis} fontSize={11} tickLine={false} />
                    <Tooltip
                      {...tooltipProps(chart)}
                      
                    />
                    <Bar dataKey="value">
                      {features.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.value >= 0 ? chart.danger : chart.ok}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Auxiliary Summary */}
              <div className="bg-inset rounded-xl p-4 border border-line flex items-start gap-3">
                <ShieldAlert className="h-5 w-5 text-brand mt-0.5 shrink-0" />
                <div>
                  <h4 className="text-xs font-semibold text-ink uppercase">SHAP Attribution Inference</h4>
                  <p className="text-xs text-ink-muted mt-1 leading-relaxed">
                    The leading feature impact is <strong className="text-ink">
                      {features.reduce((prev, curr) => Math.abs(curr.value) > Math.abs(prev.value) ? curr : prev).name}
                    </strong>. Model decision borders conform to behavioral bounds.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full min-h-[300px] flex flex-col items-center justify-center text-center p-12">
              <Cpu className="h-16 w-16 text-ink-faint mb-4" />
              <h3 className="text-lg font-semibold text-ink mb-1">Enter Transaction ID</h3>
              <p className="text-ink-muted max-w-sm text-sm">
                Enter a transaction reference ID from the logs on the left panel to execute full model attribution explainer overlays.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
