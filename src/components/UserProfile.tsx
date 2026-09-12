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
import { tooltipProps, useChartTheme } from "../lib/chartTheme";


export default function UserProfile() {
  const chart = useChartTheme();
  const { api, token, username } = useAuth();
  const [profile, setProfile] = useState<BehaviorProfile | null>(null);
  const [transactions, setTransactions] = useState<StatementTransaction[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
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
      // Both requests used to .catch(() => null) and drop the reason, so a
      // backend that was down produced the same screen as a user who had
      // simply never uploaded a statement: "No Profile Found - you haven't
      // generated a behavior profile yet." That is a false statement about the
      // user's own data, and it sent people to re-upload a statement they had
      // already uploaded. Keep the error and say which one it was.
      let failure: string | null = null;

      const p = await api<BehaviorProfile>("/api/profiles/me").catch((e: any) => {
        // A 404 here genuinely means "no profile yet"; anything else is a fault.
        if (!/\b404\b|not found/i.test(String(e?.message ?? ""))) {
          failure = e?.message || "Could not load your profile";
        }
        return null;
      });
      if (p) setProfile(p);

      const page = await api<StatementTransactionsPage>(
        "/api/statement-transactions"
      ).catch((e: any) => {
        failure = failure ?? (e?.message || "Could not load your transactions");
        return null;
      });
      if (page) {
        setTransactions(page.transactions ?? []);
        setTotalCount(page.total ?? 0);
        setTruncated(!!page.truncated);
      }

      setLoadError(failure);
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
      // Everything used to be compared with localeCompare, so the amount
      // column sorted lexically: 900 came after 1,000 and 95 after 9,500.
      // Timestamps sorted by string too, which only happened to work because
      // they are ISO.
      let cmp: number;
      if (key === "amount") {
        cmp = (Number(aVal) || 0) - (Number(bVal) || 0);
      } else if (key === "timestamp") {
        cmp = (Date.parse(String(aVal)) || 0) - (Date.parse(String(bVal)) || 0);
      } else {
        cmp = String(aVal).localeCompare(String(bVal));
      }
      return txSort.dir === "asc" ? cmp : -cmp;
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
      ? <ChevronUp className="h-3 w-3 text-brand" />
      : <ChevronDown className="h-3 w-3 text-brand" />;
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
  // merchant_frequency is deliberately the top 10, so Object.keys().length
  // could never report more than 10 unique payees however large the statement.
  // distinct_payees is the real count.
  const uniqueMerchants =
    profile?.distinct_payees ??
    (profile?.merchant_frequency
      ? Object.keys(profile.merchant_frequency).length
      : new Set(transactions.map(tx => tx.merchant)).size);

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
    const failed = loadError !== null;
    return (
      <div className="space-y-8 animate-fade-in h-full flex flex-col" id="user-profile-container">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">My Profile</h1>
          <p className="text-ink-muted">View your personalized payment behavior statistics.</p>
        </div>
        <div className="bg-surface/40 border border-line rounded-xl p-12 text-center flex-1 flex flex-col justify-center items-center">
          <User className={`h-16 w-16 mb-4 ${failed ? "text-warn" : "text-ink-faint"}`} />
          <h3 className="text-lg font-semibold text-ink mb-1">
            {failed ? "Couldn't load your profile" : "No Profile Found"}
          </h3>
          <p className="text-ink-muted max-w-md text-sm">
            {failed
              ? `Your data may well be there - this screen could not reach it. ${loadError}`
              : "You haven't generated a behavior profile yet. Head over to the Upload Statement page to extract your data."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in" id="user-profile-container">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">My Profile</h1>
        <p className="text-ink-muted">
          Personalized payment behavior dashboard for <span className="font-semibold text-brand">{username}</span>.
          {transactions.length > 0 && (
            <span className="text-ink-subtle ml-2">
              · {totalCount} transactions extracted
              {truncated && ` (showing the most recent ${transactions.length})`}
            </span>
          )}
        </p>
      </div>

      {profile && (profile.transactions_without_time ?? 0) > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/20 text-warn text-sm rounded-lg p-4 flex items-start gap-3">
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
          <div className="bg-gradient-to-br from-indigo-600/10 to-surface border border-indigo-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-brand/70 uppercase">Transactions</span>
              <Activity className="h-4 w-4 text-brand" />
            </div>
            <div className="text-2xl font-bold text-ink">{profile.transaction_count}</div>
            <div className="text-xs text-ink-subtle mt-1">Total analyzed</div>
          </div>

          <div className="bg-gradient-to-br from-violet-600/10 to-surface border border-violet-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-violet-700/70 dark:text-violet-300/70 uppercase">Avg Ticket</span>
              <DollarSign className="h-4 w-4 text-violet-700 dark:text-violet-400" />
            </div>
            <div className="text-2xl font-bold text-ink">₹{profile.avg_amount?.toLocaleString("en-IN")}</div>
            <div className="text-xs text-ink-subtle mt-1">Mean txn size</div>
          </div>

          <div className="bg-gradient-to-br from-rose-600/10 to-surface border border-rose-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-danger/70 uppercase">Peak Ticket</span>
              <TrendingUp className="h-4 w-4 text-danger" />
            </div>
            <div className="text-2xl font-bold text-ink">₹{profile.max_amount?.toLocaleString("en-IN")}</div>
            <div className="text-xs text-ink-subtle mt-1">Highest single txn</div>
          </div>

          <div className="bg-gradient-to-br from-amber-600/10 to-surface border border-amber-500/20 rounded-xl p-4">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-warn/70 uppercase">Active Hour</span>
              <Clock className="h-4 w-4 text-warn" />
            </div>
            <div className="text-2xl font-bold text-ink">
              {profile.most_active_hour !== null && profile.most_active_hour !== undefined
                ? `${String(profile.most_active_hour).padStart(2, "0")}:00`
                : "Not in statement"}
            </div>
            <div className="text-xs text-ink-subtle mt-1">
              {profile.most_active_hour !== null && profile.most_active_hour !== undefined
                ? "Most recurring"
                : "No transaction times to read"}
            </div>
          </div>

          <div className="bg-gradient-to-br from-emerald-600/10 to-surface border border-emerald-500/20 rounded-xl p-4 hidden xl:block">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs font-semibold text-ok/70 uppercase">Merchants</span>
              <CreditCard className="h-4 w-4 text-ok" />
            </div>
            <div className="text-2xl font-bold text-ink">{uniqueMerchants}</div>
            <div className="text-xs text-ink-subtle mt-1">Unique payees</div>
          </div>
        </div>
      )}

      {/* ── Charts Row ── */}
      {profile && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Merchant Frequency */}
          <div className="bg-surface border border-line rounded-xl p-5">
            <h3 className="text-base font-semibold text-ink mb-4 flex items-center gap-2">
              <CreditCard className="h-4 w-4 text-brand" />
              Top Merchants
            </h3>
            <div className="h-64">
              {getFrequencyData().length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={getFrequencyData()} barSize={28}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                    <XAxis dataKey="name" stroke={chart.axis} fontSize={10} tickLine={false} angle={-20} textAnchor="end" height={50} />
                    <YAxis stroke={chart.axis} fontSize={11} tickLine={false} />
                    <Tooltip
                      {...tooltipProps(chart)}
                      
                    />
                    <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                      {getFrequencyData().map((_, i) => (
                        <Cell key={i} fill={chart.series[i % chart.series.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-ink-subtle text-sm">No merchant data</div>
              )}
            </div>
          </div>

          {/* Monthly Volume */}
          <div className="bg-surface border border-line rounded-xl p-5">
            <h3 className="text-base font-semibold text-ink mb-4 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-danger" />
              Monthly UPI Volume
            </h3>
            <div className="h-64">
              {getMonthlyData().length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={getMonthlyData()}>
                    <defs>
                      <linearGradient id="monthGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={chart.brand} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={chart.brand} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                    <XAxis dataKey="month" stroke={chart.axis} fontSize={11} tickLine={false} />
                    <YAxis stroke={chart.axis} fontSize={11} tickLine={false} />
                    <Tooltip
                      {...tooltipProps(chart)}
                      
                      formatter={(value: number) => [`₹${value.toLocaleString("en-IN")}`, "Volume"]}
                    />
                    <Area type="monotone" dataKey="total" stroke={chart.brand} strokeWidth={2.5} fill="url(#monthGrad)" dot={{ r: 4, fill: chart.brand }} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-ink-subtle text-sm">No monthly data</div>
              )}
            </div>
          </div>

          {/* Hourly Distribution */}
          <div className="bg-surface border border-line rounded-xl p-5">
            <h3 className="text-base font-semibold text-ink mb-4 flex items-center gap-2">
              <Clock className="h-4 w-4 text-warn" />
              Hourly Activity Distribution
            </h3>
            <div className="h-64">
              {getHourlyData().some(d => d.count > 0) ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={getHourlyData()} barSize={12}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                    <XAxis dataKey="hour" stroke={chart.axis} fontSize={9} tickLine={false} interval={2} />
                    <YAxis stroke={chart.axis} fontSize={11} tickLine={false} />
                    <Tooltip
                      {...tooltipProps(chart)}
                      
                    />
                    <Bar dataKey="count" fill={chart.warn} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-ink-subtle text-sm">No hourly data</div>
              )}
            </div>
          </div>

          {/* Merchant Distribution Pie */}
          <div className="bg-surface border border-line rounded-xl p-5">
            <h3 className="text-base font-semibold text-ink mb-4 flex items-center gap-2">
              <Activity className="h-4 w-4 text-violet-700 dark:text-violet-400" />
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
                        <Cell key={i} fill={chart.series[i % chart.series.length]} stroke="none" />
                      ))}
                    </Pie>
                    <Tooltip
                      {...tooltipProps(chart)}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-ink-subtle text-sm">No distribution data</div>
              )}
              {/* Legend */}
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 justify-center">
                {getMerchantPieData().map((item, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs text-ink-muted">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: chart.series[i % chart.series.length] }} />
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
        <div className="bg-surface border border-line rounded-xl p-5">
          <h3 className="text-base font-semibold text-ink mb-3 flex items-center gap-2">
            <Activity className="h-4 w-4 text-brand" />
            Auxiliary Parameters
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 text-sm text-ink-muted">
            <div className="p-3 bg-inset/60 rounded-lg border border-line/50">
              <span className="text-ink-subtle block mb-1 text-xs uppercase font-semibold">Night Txn Ratio</span>
              {(() => {
                // night_transactions only counts rows that carried a clock
                // time, so transaction_count is the wrong denominator: on a
                // statement where half the rows print no time this halved the
                // ratio. Divide by the rows the count was taken over, and say
                // so, rather than quietly reporting a smaller number.
                const timed = profile.timed_transaction_count ?? profile.transaction_count;
                return (
                  <>
                    <span className="font-semibold text-ink">
                      {timed > 0 ? Math.round((profile.night_transactions / timed) * 100) : 0}%
                    </span>
                    <span className="text-ink-subtle text-xs ml-1">
                      ({profile.night_transactions} of {timed} timed)
                    </span>
                  </>
                );
              })()}
            </div>
            <div className="p-3 bg-inset/60 rounded-lg border border-line/50">
              <span className="text-ink-subtle block mb-1 text-xs uppercase font-semibold">Weekend Activity</span>
              <span className="font-semibold text-ink">{profile.weekend_transactions}</span>
              <span className="text-ink-subtle text-xs ml-1">transactions</span>
            </div>
            <div className="p-3 bg-inset/60 rounded-lg border border-line/50">
              <span className="text-ink-subtle block mb-1 text-xs uppercase font-semibold">Daily Avg</span>
              <span className="font-semibold text-ink">{profile.average_daily_transactions}</span>
              <span className="text-ink-subtle text-xs ml-1">txs/day</span>
            </div>
            <div className="p-3 bg-inset/60 rounded-lg border border-line/50">
              <span className="text-ink-subtle block mb-1 text-xs uppercase font-semibold">Failed Rate</span>
              <span className="font-semibold text-ink">
                {profile.failed_transactions} / {profile.transaction_count}
              </span>
              <span className="text-ink-subtle text-xs ml-1">
                ({profile.transaction_count > 0 ? Math.round((profile.failed_transactions / profile.transaction_count) * 100) : 0}%)
              </span>
            </div>
          </div>

          {/* Known UPI IDs */}
          {profile.known_upi_ids && profile.known_upi_ids.length > 0 && (
            <div className="mt-4 pt-4 border-t border-line/50">
              <span className="text-xs font-semibold text-ink-subtle uppercase block mb-2">Known UPI IDs</span>
              <div className="flex flex-wrap gap-2">
                {profile.known_upi_ids.map((upi, i) => (
                  <span key={i} className="px-2.5 py-1 bg-indigo-500/10 border border-indigo-500/20 text-brand rounded-full text-xs font-mono">
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
        <div className="bg-surface border border-line rounded-xl overflow-hidden" id="transactions-table-container">
          <div className="p-5 border-b border-line flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-ink flex items-center gap-2">
                <CreditCard className="h-4 w-4 text-brand" />
                Extracted Transactions
              </h3>
              <p className="text-xs text-ink-subtle mt-0.5">
                {filteredTxs.length} of {transactions.length} transactions
                {totalSpent > 0 && <> · Total volume: <span className="text-ink-muted">₹{totalSpent.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span></>}
              </p>
            </div>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-ink-subtle" />
              <input
                type="text"
                value={txSearch}
                onChange={e => { setTxSearch(e.target.value); setTxPage(0); }}
                placeholder="Search merchant, UPI ID, amount…"
                className="pl-9 pr-3 py-2 text-sm bg-inset border border-line rounded-lg text-ink-muted placeholder-ink-subtle focus:outline-none focus:border-indigo-500/50 w-full sm:w-72 transition"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-inset/60">
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
                      className="px-4 py-3 text-left text-xs font-semibold text-ink-subtle uppercase tracking-wider cursor-pointer hover:text-ink-muted transition select-none"
                    >
                      <div className="flex items-center gap-1">
                        {col.label}
                        <SortIcon colKey={col.key} />
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50">
                {visibleTxs.map((tx, idx) => (
                  <tr key={idx} className="hover:bg-raised/30 transition">
                    <td className="px-4 py-3 whitespace-nowrap text-ink-muted text-xs font-mono">
                      {formatTimestamp(tx.timestamp)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-ink text-sm font-medium truncate max-w-[200px]" title={tx.merchant}>
                        {tx.merchant}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-semibold text-ink">₹{tx.amount?.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {tx.upi_id ? (
                        <span className="text-xs font-mono text-brand bg-indigo-500/10 px-2 py-0.5 rounded-md">{tx.upi_id}</span>
                      ) : (
                        <span className="text-ink-subtle text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                        tx.status === "SUCCESS"
                          ? "bg-emerald-500/10 text-ok border border-emerald-500/20"
                          : tx.status === "FAILED"
                            ? "bg-red-500/10 text-danger border border-red-500/20"
                            : "bg-amber-500/10 text-warn border border-amber-500/20"
                      }`}>
                        {tx.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-ink-subtle font-mono truncate max-w-[140px]" title={tx.reference_number || ""}>
                      {tx.reference_number || "—"}
                    </td>
                  </tr>
                ))}
                {visibleTxs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-ink-subtle">
                      No transactions match your search.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="p-4 border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-subtle">
                Page {txPage + 1} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setTxPage(p => Math.max(0, p - 1))}
                  disabled={txPage === 0}
                  className="px-3 py-1.5 text-xs font-medium bg-raised hover:bg-raised disabled:opacity-40 disabled:cursor-not-allowed text-ink-muted rounded-lg transition"
                >
                  Previous
                </button>
                <button
                  onClick={() => setTxPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={txPage >= totalPages - 1}
                  className="px-3 py-1.5 text-xs font-medium bg-raised hover:bg-raised disabled:opacity-40 disabled:cursor-not-allowed text-ink-muted rounded-lg transition"
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
