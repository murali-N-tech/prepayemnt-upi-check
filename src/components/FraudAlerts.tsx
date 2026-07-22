import React, { useEffect, useState } from "react";
import { AlertOctagon, CheckCircle, ShieldAlert, Calendar, DollarSign, ArrowRight } from "lucide-react";
import { Transaction } from "../types";

export default function FraudAlerts() {
  const [alerts, setAlerts] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAlerts = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/transactions");
      if (!res.ok) {
        throw new Error("Unable to read security logs");
      }
      const data: Transaction[] = await res.json();
      const filtered = data.filter(t => t.risk === 1);
      setAlerts(filtered);
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  return (
    <div className="space-y-8 animate-fade-in" id="fraud-alerts-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Real-Time Fraud Alerts</h1>
        <p className="text-slate-400">
          Displays a live stream of transactions actively flagged as HIGH risk or blocked due to behavioral anomalies.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-12">
          <div className="h-10 w-10 border-2 border-rose-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : error ? (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-xl p-4">
          {error}
        </div>
      ) : alerts.length === 0 ? (
        <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-xl p-6 flex items-start gap-4 max-w-2xl">
          <CheckCircle className="h-8 w-8 text-emerald-400 mt-0.5 shrink-0" />
          <div>
            <h3 className="text-lg font-semibold text-white">Security Stream Clear</h3>
            <p className="text-slate-300 text-sm mt-1">
              No transactions currently match threat profile rules. The live payment processing channels are fully secure.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-4 max-w-4xl" id="alerts-stream">
          {alerts.map((alert, idx) => (
            <div
              key={idx}
              className="bg-slate-900 border border-rose-500/20 hover:border-rose-500/30 rounded-xl p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 transition relative overflow-hidden"
            >
              {/* Left threat accent */}
              <div className="absolute top-0 bottom-0 left-0 w-1.5 bg-rose-500" />

              <div className="flex items-start gap-4">
                <div className="p-3 bg-rose-500/10 text-rose-400 rounded-lg shrink-0">
                  <AlertOctagon className="h-6 w-6" />
                </div>
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-xs font-bold text-rose-400 bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 rounded">
                      BLOCK TRIGGERED
                    </span>
                    <span className="text-xs text-slate-500 font-mono">ID: {alert.transaction_id}</span>
                  </div>

                  <div className="flex items-center gap-1.5 mt-2 text-base font-bold text-white flex-wrap">
                    <span className="font-mono">{alert.sender}</span>
                    <ArrowRight className="h-4 w-4 text-slate-500" />
                    <span className="font-semibold text-slate-300">{alert.receiver || "Unnamed Receiver"}</span>
                  </div>

                  <div className="flex items-center gap-4 text-xs text-slate-500 mt-2">
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" />
                      {alert.timestamp}
                    </span>
                    <span className="flex items-center gap-1">
                      <ShieldAlert className="h-3.5 w-3.5 text-rose-400" />
                      Velocity Score: {alert.velocity_score}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex md:flex-col items-end gap-3 md:gap-1 shrink-0 self-stretch md:self-auto justify-between md:justify-center border-t border-slate-800 md:border-t-0 pt-3 md:pt-0">
                <div className="flex items-center gap-1 text-2xl font-black text-rose-500">
                  <DollarSign className="h-5 w-5 -mr-1" />
                  {alert.amount}
                </div>
                <div className="text-right">
                  <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block">Threat Score</span>
                  <span className="text-xs font-bold text-rose-400 font-mono">{alert.risk_score}/100</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
