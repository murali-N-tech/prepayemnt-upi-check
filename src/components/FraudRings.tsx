import React, { useEffect, useState } from "react";
import { ShieldAlert, Users, Landmark, AlertTriangle, CheckCircle } from "lucide-react";

interface FraudRing {
  merchant: string;
  users: string[];
}

export default function FraudRings() {
  const [rings, setRings] = useState<FraudRing[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRings = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/fraud-rings");
      if (!res.ok) {
        throw new Error("Unable to retrieve fraud ring diagnostics");
      }
      const data = await res.json();
      setRings(data.rings || []);
    } catch (err: any) {
      setError(err.message || "Failed to load rings data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRings();
  }, []);

  return (
    <div className="space-y-8 animate-fade-in" id="fraud-rings-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Detected Fraud Rings</h1>
        <p className="text-slate-400">
          Identifies nodes of high density where a single merchant terminal is linked to multiple user accounts, indicating systemic collusion or mule account networks.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-12">
          <div className="h-10 w-10 border-2 border-rose-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : error ? (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-xl p-4 flex items-center gap-2">
          <AlertTriangle className="h-5 w-5" />
          <span>{error}</span>
        </div>
      ) : rings.length === 0 ? (
        <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-xl p-6 flex items-start gap-4 max-w-2xl">
          <CheckCircle className="h-8 w-8 text-emerald-400 mt-0.5 shrink-0" />
          <div>
            <h3 className="text-lg font-semibold text-white">No Active Fraud Rings Detected</h3>
            <p className="text-slate-300 text-sm mt-1">
              All payment endpoints reflect singular, secure connections. No high-density user collusion networks are currently flagged in transaction histories.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {rings.map((ring, idx) => (
            <div
              key={idx}
              className="bg-slate-900 border border-rose-500/20 rounded-xl p-6 relative overflow-hidden flex flex-col justify-between"
              id={`fraud-ring-card-${idx}`}
            >
              {/* Threat Banner Accent */}
              <div className="absolute top-0 left-0 right-0 h-1 bg-rose-500" />

              <div>
                <div className="flex items-start justify-between mb-4">
                  <div className="p-3 bg-rose-500/10 text-rose-400 rounded-lg">
                    <ShieldAlert className="h-6 w-6" />
                  </div>
                  <span className="text-xs font-semibold px-2.5 py-1 bg-rose-500/15 text-rose-400 rounded-full border border-rose-500/30">
                    Density Trigger
                  </span>
                </div>

                <div className="space-y-1">
                  <span className="text-xs text-slate-500 font-semibold uppercase block">Merchant Node</span>
                  <div className="flex items-center gap-1.5 text-lg font-bold text-white">
                    <Landmark className="h-4 w-4 text-rose-400" />
                    {ring.merchant}
                  </div>
                </div>

                {/* Users List */}
                <div className="mt-6 space-y-2">
                  <span className="text-xs text-slate-500 font-semibold uppercase block">Associated Accounts ({ring.users.length})</span>
                  <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                    {ring.users.map((user, uidx) => (
                      <div key={uidx} className="flex items-center gap-2 p-2 bg-slate-950 rounded border border-slate-900/50 text-xs text-slate-300">
                        <Users className="h-3.5 w-3.5 text-indigo-400" />
                        <span className="font-mono">{user}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-400 flex justify-between items-center">
                <span>COLLUSION CHANNELS</span>
                <span className="font-bold text-rose-400">{ring.users.length} connected</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
