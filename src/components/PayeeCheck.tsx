import { useState } from "react";
import {
  ScanLine, ShieldCheck, ShieldAlert, ShieldX, AlertTriangle, Info,
  Flag, Users, CalendarClock, Repeat, Loader2, IndianRupee,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { PayeeCheckResult } from "../types";

const DECISION_STYLE: Record<string, { ring: string; text: string; Icon: typeof ShieldCheck }> = {
  APPROVE: { ring: "bg-emerald-500/10 border-emerald-500/20", text: "text-ok", Icon: ShieldCheck },
  WARN:    { ring: "bg-amber-500/10 border-amber-500/20",     text: "text-warn",   Icon: AlertTriangle },
  STEP_UP: { ring: "bg-orange-500/10 border-orange-500/20",   text: "text-orange-700 dark:text-orange-400",  Icon: ShieldAlert },
  BLOCK:   { ring: "bg-rose-500/10 border-rose-500/20",       text: "text-danger",    Icon: ShieldX },
};

const DECISION_LABEL: Record<string, string> = {
  APPROVE: "Looks safe",
  WARN: "Check first",
  STEP_UP: "Verify the payee",
  BLOCK: "Do not pay",
};

const SEVERITY_STYLE: Record<string, string> = {
  critical: "border-rose-500/30 bg-rose-500/5 text-danger",
  high: "border-orange-500/30 bg-orange-500/5 text-orange-700 dark:text-orange-300",
  warn: "border-amber-500/30 bg-amber-500/5 text-warn",
  info: "border-line bg-inset/60 text-ink-muted",
};

const EXAMPLES = [
  { label: "Legitimate shop QR", value: "upi://pay?pa=demo-chaipoint@okhdfcbank&pn=Chai%20Point&am=40&cu=INR" },
  { label: "Tampered QR sticker", value: "upi://pay?pa=rakesh9911@ybl&pn=Reliance%20Digital&am=48999" },
  { label: "Fake bank refund", value: "sbi-refund@okaxis" },
  { label: "Collection account", value: "demo-mule@ybl" },
];

export default function PayeeCheck() {
  const { api } = useAuth();
  const [payload, setPayload] = useState("");
  const [amount, setAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PayeeCheckResult | null>(null);
  const [reported, setReported] = useState(false);

  const runCheck = async (value?: string) => {
    const target = (value ?? payload).trim();
    if (!target) {
      setError("Paste a UPI ID, a QR code's contents, or a phone number.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setReported(false);
    try {
      const data = await api<PayeeCheckResult>("/api/payee/check", {
        method: "POST",
        body: JSON.stringify({ payload: target, amount: amount ? parseFloat(amount) : null }),
      });
      setResult(data);
    } catch (err: any) {
      setError(err.message || "Could not run the check.");
    } finally {
      setLoading(false);
    }
  };

  const reportPayee = async () => {
    if (!result?.payee.vpa) return;
    try {
      await api("/api/payee/report", {
        method: "POST",
        body: JSON.stringify({ vpa: result.payee.vpa, reason: "Reported from the payee check" }),
      });
      setReported(true);
    } catch (err: any) {
      setError(err.message || "Could not send the report.");
    }
  };

  const style = result ? DECISION_STYLE[result.decision] ?? DECISION_STYLE.WARN : null;
  const rep = result?.reputation;

  return (
    <div className="space-y-8 animate-fade-in" id="payee-check-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">Check a payee</h1>
        <p className="text-ink-muted max-w-3xl">
          Checks who you are about to pay, before the money moves. Every other page here
          scores your own behaviour, which cannot tell that a first payment to a scammer
          is a scam. This looks at the address instead.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Input */}
        <div className="bg-surface border border-line rounded-xl p-6 h-fit">
          <h2 className="text-xl font-semibold text-ink mb-4">Payee details</h2>

          <form
            onSubmit={(e) => { e.preventDefault(); runCheck(); }}
            className="space-y-4"
          >
            <div>
              <label className="block text-sm font-medium text-ink-muted mb-1">
                UPI ID, QR contents, or phone number
              </label>
              <textarea
                value={payload}
                onChange={(e) => setPayload(e.target.value)}
                rows={3}
                placeholder="name@bank   ·   upi://pay?pa=...   ·   9876543210"
                className="w-full px-4 py-2 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle font-mono text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-ink-muted mb-1">
                Amount (optional)
              </label>
              <div className="relative">
                <IndianRupee className="h-4 w-4 text-ink-subtle absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="How much are you sending?"
                  className="w-full pl-9 pr-4 py-2 bg-inset border border-line rounded-lg text-ink placeholder-ink-subtle focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-danger text-sm rounded-lg p-3">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 text-white font-medium rounded-lg transition flex items-center justify-center gap-2"
            >
              {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <><ScanLine className="h-4 w-4" /> Check this payee</>}
            </button>
          </form>

          <div className="mt-6 pt-5 border-t border-line">
            <p className="text-xs font-semibold text-ink-subtle uppercase tracking-wider mb-3">
              Try an example
            </p>
            <div className="space-y-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.label}
                  onClick={() => { setPayload(ex.value); runCheck(ex.value); }}
                  className="w-full text-left px-3 py-2 text-sm text-ink-muted bg-inset hover:bg-raised/60 border border-line rounded-lg transition"
                >
                  {ex.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Result */}
        <div className="lg:col-span-2 space-y-6">
          {result && style ? (
            <>
              <div className={`border rounded-xl p-6 flex flex-col md:flex-row md:items-center justify-between gap-6 ${style.ring}`}>
                <div className="flex items-start gap-4">
                  <style.Icon className={`h-12 w-12 shrink-0 mt-1 ${style.text}`} />
                  <div>
                    <h3 className="text-2xl font-bold text-ink">
                      {DECISION_LABEL[result.decision] ?? result.decision}
                    </h3>
                    <p className="text-ink-muted text-sm mt-1">{result.headline}</p>
                    {result.payee.vpa && (
                      <p className="text-xs font-mono text-ink-muted mt-2">
                        {result.payee.vpa}
                        {result.payee.display_name && ` · shown as "${result.payee.display_name}"`}
                      </p>
                    )}
                  </div>
                </div>
                <div className="text-center shrink-0">
                  <div className="text-xs text-ink-muted uppercase font-semibold">Payee risk</div>
                  <div className="text-5xl font-black text-ink mt-1">{result.risk_score}</div>
                  <div className="text-xs text-ink-muted mt-1">out of 100</div>
                </div>
              </div>

              {/* Findings */}
              <div className="bg-surface border border-line rounded-xl p-6">
                <h3 className="text-lg font-semibold text-ink mb-4">What the check found</h3>
                <ul className="space-y-2.5">
                  {result.findings.map((f, i) => (
                    <li key={i} className={`text-sm rounded-lg p-3 border ${SEVERITY_STYLE[f.severity] ?? SEVERITY_STYLE.info}`}>
                      <span className="uppercase text-[10px] font-bold tracking-wider mr-2 opacity-70">
                        {f.severity}
                      </span>
                      {f.message}
                    </li>
                  ))}
                  {result.findings.length === 0 && (
                    <li className="text-sm text-ink-muted">Nothing stood out about this payee.</li>
                  )}
                </ul>
              </div>

              {/* Reputation */}
              <div className="bg-surface border border-line rounded-xl p-6">
                <h3 className="text-lg font-semibold text-ink mb-1">Payee history</h3>
                <p className="text-xs text-ink-subtle mb-4">
                  Pooled across everyone using this system. A single wallet app cannot see this.
                </p>

                {rep?.known ? (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {[
                      { Icon: CalendarClock, label: "First seen", value: rep.age_days !== null ? `${rep.age_days} days ago` : "unknown" },
                      { Icon: Users, label: "People who paid", value: String(rep.distinct_payers) },
                      { Icon: Repeat, label: "Paid more than once", value: String(rep.repeat_payers) },
                      { Icon: Flag, label: "Reports", value: String(rep.reports) },
                    ].map(({ Icon, label, value }) => (
                      <div key={label} className="bg-inset border border-line/60 rounded-lg p-3">
                        <Icon className="h-4 w-4 text-brand mb-2" />
                        <div className="text-lg font-bold text-ink leading-tight">{value}</div>
                        <div className="text-[11px] text-ink-subtle mt-0.5">{label}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex items-start gap-3 text-sm text-ink-muted bg-inset border border-line rounded-lg p-4">
                    <Info className="h-5 w-5 shrink-0 text-ink-subtle mt-0.5" />
                    <span>
                      Nobody using this system has paid this address before. That is normal for a
                      new shop, and it is also what a freshly created account looks like.
                    </span>
                  </div>
                )}

                {result.payee.vpa && (
                  <button
                    onClick={reportPayee}
                    disabled={reported}
                    className="mt-5 flex items-center gap-2 text-sm px-4 py-2 rounded-lg border border-line text-ink-muted hover:bg-raised/60 disabled:opacity-50 disabled:cursor-default transition"
                  >
                    <Flag className="h-4 w-4" />
                    {reported ? "Reported — thank you" : "Report this payee"}
                  </button>
                )}
              </div>

              {/* Score breakdown */}
              <div className="bg-surface border border-line rounded-xl p-6">
                <h3 className="text-sm font-semibold text-ink mb-4">Where the score came from</h3>
                <div className="space-y-3">
                  {[
                    ["Address and QR contents", result.component_scores.address_and_qr],
                    ["Payee history", result.component_scores.payee_history],
                    ["Amount in context", result.component_scores.amount_context],
                  ].map(([label, value]) => (
                    <div key={label as string}>
                      <div className="flex justify-between text-xs text-ink-muted mb-1">
                        <span>{label}</span>
                        <span className="font-mono text-ink-muted">{value as number}</span>
                      </div>
                      <div className="h-1.5 bg-inset rounded-full overflow-hidden">
                        <div
                          className="h-full bg-indigo-500 rounded-full"
                          style={{ width: `${Math.min(100, value as number)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                {result.payer_behaviour && (
                  <p className="text-xs text-ink-subtle mt-4 pt-4 border-t border-line">
                    Against your own history this payment scores{" "}
                    <span className="text-ink-muted font-semibold">
                      {result.payer_behaviour.risk_score} ({result.payer_behaviour.risk_level})
                    </span>.
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="bg-surface/40 border border-line rounded-xl p-12 text-center h-full flex flex-col justify-center items-center">
              <ScanLine className="h-16 w-16 text-ink-faint mb-4" />
              <h3 className="text-lg font-semibold text-ink mb-1">Check before you pay</h3>
              <p className="text-ink-muted max-w-md text-sm">
                Paste a UPI ID or the contents of a QR code on the left, or try one of the
                examples, to see what this system knows about the payee.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
