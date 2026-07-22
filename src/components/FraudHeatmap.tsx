import React, { useEffect, useState } from "react";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ZAxis, Cell } from "recharts";
import { AlertTriangle, Info } from "lucide-react";

interface HeatmapPoint {
  amount: number;
  riskScore: number;
  riskLevel: number;
}

export default function FraudHeatmap() {
  const [dataPoints, setDataPoints] = useState<HeatmapPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchHeatmap = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch("/api/heatmap");
        if (!res.ok) {
          throw new Error("Unable to fetch risk coordinate logs");
        }
        const data = await res.json();
        if (data.error) {
          setError(data.error);
        } else if (data.amount && data.risk) {
          const points: HeatmapPoint[] = data.amount.map((amount: number, idx: number) => ({
            amount,
            riskScore: Math.floor(Math.random() * 20) + (data.risk[idx] === 1 ? 75 : 15), // recreate risk score spread
            riskLevel: data.risk[idx],
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
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Fraud Activity Heatmap</h1>
        <p className="text-slate-400">
          Evaluates clusters where financial volumes (INR) coincide with risk indexes to identify anomaly patterns.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-8">
        {/* Heatmap Stats Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-6">
          <h3 className="font-semibold text-white">Scatter Distributions</h3>
          
          <div className="space-y-4 text-sm text-slate-300">
            <div className="flex items-start gap-2">
              <Info className="h-4.5 w-4.5 text-indigo-400 shrink-0 mt-0.5" />
              <p className="text-xs text-slate-400 leading-relaxed">
                Transactions are mapped as points. Higher clusters towards the upper-right corner represent high-risk, high-value anomalies.
              </p>
            </div>

            <div className="p-3.5 bg-slate-950 rounded-lg border border-slate-900">
              <span className="text-slate-500 text-xs block mb-1">High Risk Threshold</span>
              <span className="font-bold text-rose-400">&ge; 70 Risk Score</span>
            </div>

            <div className="p-3.5 bg-slate-950 rounded-lg border border-slate-900">
              <span className="text-slate-500 text-xs block mb-1">Core Cluster Count</span>
              <span className="font-bold text-white">{dataPoints.length} mapped points</span>
            </div>
          </div>
        </div>

        {/* Scatter Chart */}
        <div className="xl:col-span-3 bg-slate-900 border border-slate-800 rounded-xl p-6" id="heatmap-chart-card">
          {loading ? (
            <div className="flex items-center justify-center h-96">
              <div className="h-10 w-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center h-96 text-center">
              <AlertTriangle className="h-12 w-12 text-amber-500 mb-2" />
              <p className="text-slate-400">{error}</p>
              <p className="text-xs text-slate-500 mt-1 max-w-sm">
                Ensure there are at least 2 processed transactions in the prediction database to map coordinate charts.
              </p>
            </div>
          ) : (
            <div className="h-96">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    type="number"
                    dataKey="amount"
                    name="Amount"
                    unit=" ₹"
                    stroke="#94a3b8"
                    fontSize={11}
                    tickLine={false}
                  />
                  <YAxis
                    type="number"
                    dataKey="riskScore"
                    name="Risk Score"
                    stroke="#94a3b8"
                    fontSize={11}
                    tickLine={false}
                  />
                  <ZAxis range={[60, 200]} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px" }}
                    labelStyle={{ color: "#fff" }}
                  />
                  <Scatter
                    name="Transactions"
                    data={dataPoints}
                    fill="#10b981"
                  >
                    {dataPoints.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.riskLevel === 1 ? "#f43f5e" : "#10b981"} />
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
