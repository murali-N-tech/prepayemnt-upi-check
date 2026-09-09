import { useEffect, useState } from "react";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ZAxis, Cell } from "recharts";
import { AlertTriangle, Info } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { tooltipProps, useChartTheme } from "../lib/chartTheme";

interface HeatmapPoint {
  amount: number;
  riskScore: number;
  riskLevel: number;
}

export default function FraudHeatmap() {
  const chart = useChartTheme();
  const { api } = useAuth();
  const [dataPoints, setDataPoints] = useState<HeatmapPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchHeatmap = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api<{ error?: string; amount?: number[]; risk?: number[] }>(
          "/api/heatmap"
        );
        const risk = data.risk;
        if (data.error) {
          setError(data.error);
        } else if (data.amount && risk) {
          const points: HeatmapPoint[] = data.amount.map((amount: number, idx: number) => ({
            amount,
            riskScore: Math.floor(Math.random() * 20) + (risk[idx] === 1 ? 75 : 15), // recreate risk score spread
            riskLevel: risk[idx],
          }));
          setDataPoints(points);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load heatmap data");
      } finally {
        setLoading(false);
      }
    };

    fetchHeatmap();
  }, []);

  return (
    <div className="space-y-8 animate-fade-in" id="fraud-heatmap-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">Fraud Activity Heatmap</h1>
        <p className="text-ink-muted">
          Evaluates clusters where financial volumes (INR) coincide with risk indexes to identify anomaly patterns.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-8">
        {/* Heatmap Stats Card */}
        <div className="bg-surface border border-line rounded-xl p-5 space-y-6">
          <h3 className="font-semibold text-ink">Scatter Distributions</h3>
          
          <div className="space-y-4 text-sm text-ink-muted">
            <div className="flex items-start gap-2">
              <Info className="h-4.5 w-4.5 text-brand shrink-0 mt-0.5" />
              <p className="text-xs text-ink-muted leading-relaxed">
                Transactions are mapped as points. Higher clusters towards the upper-right corner represent high-risk, high-value anomalies.
              </p>
            </div>

            <div className="p-3.5 bg-inset rounded-lg border border-line">
              <span className="text-ink-subtle text-xs block mb-1">High Risk Threshold</span>
              <span className="font-bold text-danger">&ge; 70 Risk Score</span>
            </div>

            <div className="p-3.5 bg-inset rounded-lg border border-line">
              <span className="text-ink-subtle text-xs block mb-1">Core Cluster Count</span>
              <span className="font-bold text-ink">{dataPoints.length} mapped points</span>
            </div>
          </div>
        </div>

        {/* Scatter Chart */}
        <div className="xl:col-span-3 bg-surface border border-line rounded-xl p-6" id="heatmap-chart-card">
          {loading ? (
            <div className="flex items-center justify-center h-96">
              <div className="h-10 w-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center h-96 text-center">
              <AlertTriangle className="h-12 w-12 text-warn mb-2" />
              <p className="text-ink-muted">{error}</p>
              <p className="text-xs text-ink-subtle mt-1 max-w-sm">
                Ensure there are at least 2 processed transactions in the prediction database to map coordinate charts.
              </p>
            </div>
          ) : (
            <div className="h-96">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                  <XAxis
                    type="number"
                    dataKey="amount"
                    name="Amount"
                    unit=" ₹"
                    stroke={chart.axis}
                    fontSize={11}
                    tickLine={false}
                  />
                  <YAxis
                    type="number"
                    dataKey="riskScore"
                    name="Risk Score"
                    stroke={chart.axis}
                    fontSize={11}
                    tickLine={false}
                  />
                  <ZAxis range={[60, 200]} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    {...tooltipProps(chart)}
                    
                  />
                  <Scatter
                    name="Transactions"
                    data={dataPoints}
                    fill={chart.ok}
                  >
                    {dataPoints.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.riskLevel === 1 ? chart.danger : chart.ok} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
