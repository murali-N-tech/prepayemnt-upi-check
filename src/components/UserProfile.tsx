import { useEffect, useState } from "react";
import {
  TrendingUp, DollarSign, Activity, User,
  Clock, CreditCard, Search, ChevronDown, ChevronUp,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, AreaChart, Area,
} from "recharts";
import { BehaviorProfile, StatementTransaction, StatementTransactionsPage } from "../types";
import { useAuth } from "../context/AuthContext";

const CHART_COLORS = ["#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd", "#818cf8", "#4f46e5", "#7c3aed", "#5b21b6", "#6d28d9", "#4338ca"];

export default function UserProfile() {
  const { api, token, username } = useAuth();
  const [profile, setProfile] = useState<BehaviorProfile | null>(null);
  const [transactions, setTransactions] = useState<StatementTransaction[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [txSearch, setTxSearch] = useState("");
  const [txSort, setTxSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "timestamp", dir: "desc" });
  const [txPage, setTxPage] = useState(0);
  const TXS_PER_PAGE = 15;

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    const fetchData = async () => {
      // Both endpoints are scoped to the signed-in user by the token, so the
      // component never asks for another account's data.
      const p = await api<BehaviorProfile>("/api/profiles/me").catch(() => null);
      if (p) setProfile(p);

      const page = await api<StatementTransactionsPage>(
        "/api/statement-transactions"
      ).catch(() => null);
      if (page) {
        setTransactions(page.transactions ?? []);
        setTotalCount(page.total ?? 0);
        setTruncated(!!page.truncated);
      }

      setLoading(false);
    };

    fetchData();
  }, [api, token]);

  // ── Chart Data Helpers ──

  const getFrequencyData = () => {
    if (!profile?.merchant_frequency) return [];
    return Object.entries(profile.merchant_frequency)
      .slice(0, 8)
      .map(([name, count]) => ({
        name: name.length > 14 ? name.substring(0, 12) + "…" : name,
        count,
      }));
  };

  const getMonthlyData = () => {
    if (!profile?.monthly_totals) return [];
    return Object.entries(profile.monthly_totals).map(([month, total]) => ({
      month,
      total: Math.round(total),
    }));
  };

  const getHourlyData = () => {
    if (!profile?.hourly_distribution) return [];
    const data = [];
    for (let i = 0; i < 24; i++) {
      data.push({
        hour: `${i.toString().padStart(2, "0")}:00`,
        count: profile.hourly_distribution[String(i)] || 0,
      });
    }
    return data;
  };

  const getMerchantPieData = () => {
    if (!profile?.merchant_frequency) return [];
    return Object.entries(profile.merchant_frequency)
      .slice(0, 6)
      .map(([name, value]) => ({ name, value }));
  };

  // ── Transaction Table Helpers ──

  const filteredTxs = transactions
    .filter(tx => {
      if (!txSearch) return true;
      const q = txSearch.toLowerCase();
      return (
        tx.merchant?.toLowerCase().includes(q) ||
        tx.upi_id?.toLowerCase().includes(q) ||
        tx.reference_number?.toLowerCase().includes(q) ||
        String(tx.amount).includes(q)
      );
    })
    .sort((a, b) => {
      const key = txSort.key as keyof StatementTransaction;
      const aVal = a[key] ?? "";
      const bVal = b[key] ?? "";
      if (txSort.dir === "asc") return String(aVal).localeCompare(String(bVal));
      return String(bVal).localeCompare(String(aVal));
    });

  const totalPages = Math.ceil(filteredTxs.length / TXS_PER_PAGE);
  const visibleTxs = filteredTxs.slice(txPage * TXS_PER_PAGE, (txPage + 1) * TXS_PER_PAGE);

  const toggleSort = (key: string) => {
    setTxSort(prev =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "desc" }
    );
    setTxPage(0);
  };

  const SortIcon = ({ colKey }: { colKey: string }) => {
    if (txSort.key !== colKey) return <ChevronDown className="h-3 w-3 opacity-30" />;
    return txSort.dir === "asc"
      ? <ChevronUp className="h-3 w-3 text-indigo-400" />
      : <ChevronDown className="h-3 w-3 text-indigo-400" />;
  };

  const formatTimestamp = (ts: string) => {
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return ts;
      return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) +
        " " + d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
    } catch {
      return ts;
    }
  };

  // ── Derived Stats ──
  // Totals come from the profile where possible: the transaction list is
  // capped, so summing it would under-report on a large statement.
  const totalSpent = profile?.monthly_totals
    ? Object.values(profile.monthly_totals).reduce((sum, v) => sum + v, 0)
    : transactions.reduce((sum, tx) => sum + (tx.amount || 0), 0);
  const uniqueMerchants = profile?.merchant_frequency
    ? Object.keys(profile.merchant_frequency).length
    : new Set(transactions.map(tx => tx.merchant)).size;

  // ── Loading State ──

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="h-8 w-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // ── Empty State ──

  if (!profile && totalCount === 0) {
    return (
      <div className="space-y-8 animate-fade-in h-full flex flex-col" id="user-profile-container">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white mb-2">My Profile</h1>
          <p className="text-slate-400">View your personalized payment behavior statistics.</p>
        </div>
        <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-12 text-center flex-1 flex flex-col justify-center items-center">
          <User className="h-16 w-16 text-slate-700 mb-4" />
          <h3 className="text-lg font-semibold text-white mb-1">No Profile Found</h3>
          <p className="text-slate-400 max-w-md text-sm">
            You haven't generated a behavior profile yet. Head over to the Upload Statement page to extract your data.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in" id="user-profile-container">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">My Profile</h1>
        <p className="text-slate-400">
          Personalized payment behavior dashboard for <span className="font-semibold text-indigo-400">{username}</span>.
          {transactions.length > 0 && (
            <span className="text-slate-500 ml-2">
              · {totalCount} transactions extracted
              {truncated && ` (showing the most recent ${transactions.length})`}
            </span>
          )}
        </p>
      </div>

      {profile && (profile.transactions_without_time ?? 0) > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/20 text-amber-300 text-sm rounded-lg p-4 flex items-start gap-3">
          <Clock className="h-5 w-5 shrink-0 mt-0.5" />
          <span>
            {profile.transactions_without_time} of {profile.transaction_count} transactions
            in your statement carry a date but no time of day
            {profile.most_active_hour === null || profile.most_active_hour === undefined
              ? ", so the hourly charts and the night-time risk rule have nothing to read"
              : ", so the hourly charts are based on the rest"}
            . A statement that includes transaction times gives a sharper profile.
          </span>
        </div>
      )}

      {/* ── Metrics Strip ── */}
      {profile && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-5 gap-4" id="metrics-grid">
          <div className="bg-gradient-to-br from-indigo-600/10 to-slate-900 border border-indigo-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-indigo-300/70 uppercase">Transactions</span>
              <Activity className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="text-2xl font-bold text-white">{profile.transaction_count}</div>
            <div className="text-xs text-slate-500 mt-1">Total analyzed</div>
          </div>

          <div className="bg-gradient-to-br from-violet-600/10 to-slate-900 border border-violet-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-violet-300/70 uppercase">Avg Ticket</span>
              <DollarSign className="h-4 w-4 text-violet-400" />
            </div>
            <div className="text-2xl font-bold text-white">₹{profile.avg_amount?.toLocaleString("en-IN")}</div>
            <div className="text-xs text-slate-500 mt-1">Mean txn size</div>
          </div>

          <div className="bg-gradient-to-br from-rose-600/10 to-slate-900 border border-rose-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-rose-300/70 uppercase">Peak Ticket</span>
              <TrendingUp className="h-4 w-4 text-rose-400" />
            </div>
            <div className="text-2xl font-bold text-white">₹{profile.max_amount?.toLocaleString("en-IN")}</div>
            <div className="text-xs text-slate-500 mt-1">Highest single txn</div>
          </div>

          <div className="bg-gradient-to-br from-amber-600/10 to-slate-900 border border-amber-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-amber-300/70 uppercase">Active Hour</span>
              <Clock className="h-4 w-4 text-amber-400" />
            </div>
            <div className="text-2xl font-bold text-white">
              {profile.most_active_hour !== null && profile.most_active_hour !== undefined
                ? `${String(profile.most_active_hour).padStart(2, "0")}:00`
                : "Not in statement"}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {profile.most_active_hour !== null && profile.most_active_hour !== undefined
                ? "Most recurring"
                : "No transaction times to read"}
            </div>
          </div>

          <div className="bg-gradient-to-br from-emerald-600/10 to-slate-900 border border-emerald-500/20 rounded-xl p-4 hidden xl:block">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-emerald-300/70 uppercase">Merchants</span>
              <CreditCard className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="text-2xl font-bold text-white">{uniqueMerchants}</div>
            <div className="text-xs text-slate-500 mt-1">Unique payees</div>
          </div>
        </div>
      )}

      {/* ── Charts Row ── */}
      {profile && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Merchant Frequency */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-base font-semibold text-white mb-4 flex items-center gap-2">
              <CreditCard className="h-4 w-4 text-indigo-400" />
              Top Merchants
            </h3>
            <div className="h-64">
              {getFrequencyData().length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={getFrequencyData()} barSize={28}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={10} tickLine={false} angle={-20} textAnchor="end" height={50} />
                    <YAxis stroke="#64748b" fontSize={11} tickLine={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px", fontSize: "12px" }}
                      labelStyle={{ color: "#fff" }}
                    />
                    <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                      {getFrequencyData().map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-slate-600 text-sm">No merchant data</div>
              )}
            </div>
          </div>

          {/* Monthly Volume */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-base font-semibold text-white mb-4 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-rose-400" />
              Monthly UPI Volume
            </h3>
            <div className="h-64">
              {getMonthlyData().length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={getMonthlyData()}>
                    <defs>
                      <linearGradient id="monthGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="month" stroke="#64748b" fontSize={11} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={11} tickLine={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px", fontSize: "12px" }}
                      labelStyle={{ color: "#fff" }}
                      formatter={(value: number) => [`₹${value.toLocaleString("en-IN")}`, "Volume"]}
                    />
                    <Area type="monotone" dataKey="total" stroke="#f43f5e" strokeWidth={2.5} fill="url(#monthGrad)" dot={{ r: 4, fill: "#f43f5e" }} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-slate-600 text-sm">No monthly data</div>
              )}
            </div>
          </div>

          {/* Hourly Distribution */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-base font-semibold text-white mb-4 flex items-center gap-2">
              <Clock className="h-4 w-4 text-amber-400" />
              Hourly Activity Distribution
            </h3>
            <div className="h-64">
              {getHourlyData().some(d => d.count > 0) ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={getHourlyData()} barSize={12}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="hour" stroke="#64748b" fontSize={9} tickLine={false} interval={2} />
                    <YAxis stroke="#64748b" fontSize={11} tickLine={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px", fontSize: "12px" }}
                      labelStyle={{ color: "#fff" }}
                    />
                    <Bar dataKey="count" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-slate-600 text-sm">No hourly data</div>
              )}
            </div>
          </div>

          {/* Merchant Distribution Pie */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-base font-semibold text-white mb-4 flex items-center gap-2">
              <Activity className="h-4 w-4 text-violet-400" />
              Payment Distribution
            </h3>
            <div className="h-64">
              {getMerchantPieData().length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={getMerchantPieData()}
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={90}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {getMerchantPieData().map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} stroke="none" />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px", fontSize: "12px" }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-slate-600 text-sm">No distribution data</div>
              )}
              {/* Legend */}
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 justify-center">
                {getMerchantPieData().map((item, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs text-slate-400">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                    {item.name.length > 16 ? item.name.substring(0, 14) + "…" : item.name}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Auxiliary Insights ── */}
      {profile && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2">
            <Activity className="h-4 w-4 text-indigo-400" />
            Auxiliary Parameters
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 text-sm text-slate-300">
            <div className="p-3 bg-slate-950/60 rounded-lg border border-slate-800/50">
              <span className="text-slate-500 block mb-1 text-xs uppercase font-semibold">Night Txn Ratio</span>
              <span className="font-semibold text-white">
                {profile.transaction_count > 0
                  ? Math.round((profile.night_transactions / profile.transaction_count) * 100)
                  : 0}%
              </span>
              <span className="text-slate-500 text-xs ml-1">({profile.night_transactions} txns)</span>
            </div>
            <div className="p-3 bg-slate-950/60 rounded-lg border border-slate-800/50">
              <span className="text-slate-500 block mb-1 text-xs uppercase font-semibold">Weekend Activity</span>
              <span className="font-semibold text-white">{profile.weekend_transactions}</span>
              <span className="text-slate-500 text-xs ml-1">transactions</span>
            </div>
            <div className="p-3 bg-slate-950/60 rounded-lg border border-slate-800/50">
              <span className="text-slate-500 block mb-1 text-xs uppercase font-semibold">Daily Avg</span>
              <span className="font-semibold text-white">{profile.average_daily_transactions}</span>
              <span className="text-slate-500 text-xs ml-1">txs/day</span>
            </div>
            <div className="p-3 bg-slate-950/60 rounded-lg border border-slate-800/50">
              <span className="text-slate-500 block mb-1 text-xs uppercase font-semibold">Failed Rate</span>
              <span className="font-semibold text-white">
                {profile.failed_transactions} / {profile.transaction_count}
              </span>
              <span className="text-slate-500 text-xs ml-1">
                ({profile.transaction_count > 0 ? Math.round((profile.failed_transactions / profile.transaction_count) * 100) : 0}%)
              </span>
            </div>
          </div>

          {/* Known UPI IDs */}
          {profile.known_upi_ids && profile.known_upi_ids.length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-800/50">
              <span className="text-xs font-semibold text-slate-500 uppercase block mb-2">Known UPI IDs</span>
              <div className="flex flex-wrap gap-2">
                {profile.known_upi_ids.map((upi, i) => (
                  <span key={i} className="px-2.5 py-1 bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 rounded-full text-xs font-mono">
                    {upi}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Extracted Transactions Table ── */}
      {transactions.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden" id="transactions-table-container">
          <div className="p-5 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <CreditCard className="h-4 w-4 text-indigo-400" />
                Extracted Transactions
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                {filteredTxs.length} of {transactions.length} transactions
                {totalSpent > 0 && <> · Total volume: <span className="text-slate-300">₹{totalSpent.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span></>}
              </p>
            </div>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
              <input
                type="text"
                value={txSearch}
                onChange={e => { setTxSearch(e.target.value); setTxPage(0); }}
                placeholder="Search merchant, UPI ID, amount…"
                className="pl-9 pr-3 py-2 text-sm bg-slate-950 border border-slate-800 rounded-lg text-slate-300 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50 w-full sm:w-72 transition"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-950/60">
                  {[
                    { key: "timestamp", label: "Date & Time" },
                    { key: "merchant", label: "Merchant / Payee" },
                    { key: "amount", label: "Amount" },
                    { key: "upi_id", label: "UPI ID" },
                    { key: "status", label: "Status" },
                    { key: "reference_number", label: "Reference" },
                  ].map(col => (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:text-slate-300 transition select-none"
                    >
                      <div className="flex items-center gap-1">
                        {col.label}
                        <SortIcon colKey={col.key} />
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {visibleTxs.map((tx, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/30 transition">
                    <td className="px-4 py-3 whitespace-nowrap text-slate-300 text-xs font-mono">
                      {formatTimestamp(tx.timestamp)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-white text-sm font-medium truncate max-w-[200px]" title={tx.merchant}>
                        {tx.merchant}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-semibold text-white">₹{tx.amount?.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {tx.upi_id ? (
                        <span className="text-xs font-mono text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded-md">{tx.upi_id}</span>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                        tx.status === "SUCCESS"
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                          : tx.status === "FAILED"
                            ? "bg-red-500/10 text-red-400 border border-red-500/20"
                            : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                      }`}>
                        {tx.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500 font-mono truncate max-w-[140px]" title={tx.reference_number || ""}>
                      {tx.reference_number || "—"}
                    </td>
                  </tr>
                ))}
                {visibleTxs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-600">
                      No transactions match your search.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="p-4 border-t border-slate-800 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                Page {txPage + 1} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setTxPage(p => Math.max(0, p - 1))}
                  disabled={txPage === 0}
                  className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300 rounded-lg transition"
                >
                  Previous
                </button>
                <button
                  onClick={() => setTxPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={txPage >= totalPages - 1}
                  className="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300 rounded-lg transition"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
