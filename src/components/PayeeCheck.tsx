import { useEffect, useState } from "react";
import { amountProblem, describeCap, rupeeInputProps } from "../lib/upiLimits";
import QrScanner from "./QrScanner";
import { useLastCheck } from "../context/CheckContext";
import {
  ScanLine, ShieldCheck, ShieldAlert, ShieldX, AlertTriangle, Info,
  Flag, Users, CalendarClock, Repeat, Loader2, IndianRupee, MessageSquareWarning, Lock,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { IntentOption, PayeeCheckResult } from "../types";

/* ── Decision styling ──────────────────────────────────────────────────────── */
const DECISION_META: Record<string, {
  gradient: string;
  border: string;
  glow: string;
  text: string;
  Icon: typeof ShieldCheck;
}> = {
  APPROVE: {
    gradient: "linear-gradient(135deg, color-mix(in oklab, var(--ok) 10%, transparent), color-mix(in oklab, var(--ok) 6%, transparent))",
    border:   "color-mix(in oklab, var(--ok) 30%, transparent)",
    glow:     "0 4px 20px var(--glow-ok, rgba(4,120,87,0.25))",
    text:     "var(--ok)",
    Icon:     ShieldCheck,
  },
  WARN: {
    gradient: "linear-gradient(135deg, color-mix(in oklab, var(--warn) 10%, transparent), color-mix(in oklab, var(--warn) 5%, transparent))",
    border:   "color-mix(in oklab, var(--warn) 30%, transparent)",
    glow:     "0 4px 20px var(--glow-warn, rgba(180,83,9,0.2))",
    text:     "var(--warn)",
    Icon:     AlertTriangle,
  },
  STEP_UP: {
    gradient: "linear-gradient(135deg, color-mix(in oklab, var(--warn) 12%, transparent), color-mix(in oklab, orange 6%, transparent))",
    border:   "color-mix(in oklab, var(--warn) 35%, transparent)",
    glow:     "0 4px 20px var(--glow-warn, rgba(180,83,9,0.25))",
    text:     "var(--warn)",
    Icon:     ShieldAlert,
  },
  BLOCK: {
    gradient: "linear-gradient(135deg, color-mix(in oklab, var(--danger) 12%, transparent), color-mix(in oklab, var(--danger) 6%, transparent))",
    border:   "color-mix(in oklab, var(--danger) 30%, transparent)",
    glow:     "0 4px 20px var(--glow-danger, rgba(220,38,38,0.25))",
    text:     "var(--danger)",
    Icon:     ShieldX,
  },
};

const DECISION_LABEL: Record<string, string> = {
  APPROVE: "Looks safe",
  WARN:    "Check first",
  STEP_UP: "Verify the payee",
  BLOCK:   "Do not pay",
};

const SEVERITY_META: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  critical: {
    bg:     "color-mix(in oklab, var(--danger) 8%, transparent)",
    border: "color-mix(in oklab, var(--danger) 25%, transparent)",
    text:   "var(--danger)",
    dot:    "var(--danger)",
  },
  high: {
    bg:     "color-mix(in oklab, var(--warn) 8%, transparent)",
    border: "color-mix(in oklab, var(--warn) 25%, transparent)",
    text:   "var(--warn)",
    dot:    "var(--warn)",
  },
  warn: {
    bg:     "color-mix(in oklab, var(--warn) 5%, transparent)",
    border: "color-mix(in oklab, var(--warn) 15%, transparent)",
    text:   "var(--warn)",
    dot:    "var(--warn)",
  },
  info: {
    bg:     "var(--inset)",
    border: "var(--line)",
    text:   "var(--ink-muted)",
    dot:    "var(--ink-faint)",
  },
};

const EXAMPLES = [
  { label: "Legitimate shop QR", value: "upi://pay?pa=demo-chaipoint@okhdfcbank&pn=Chai%20Point&am=40&cu=INR" },
  { label: "Tampered QR sticker", value: "upi://pay?pa=rakesh9911@ybl&pn=Reliance%20Digital&am=48999" },
  { label: "Fake bank refund",    value: "sbi-refund@okaxis" },
  { label: "Collection account",  value: "demo-mule@ybl" },
];

/* ── Score gauge ─────────────────────────────────────────────────────────── */
function RiskGauge({ score, color }: { score: number; color: string }) {
  const r = 40;
  const circumference = 2 * Math.PI * r;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div className="relative flex flex-col items-center">
      <svg width="100" height="100" viewBox="0 0 100 100" className="rotate-[-90deg]">
        <circle cx="50" cy="50" r={r} fill="none" stroke="var(--raised)" strokeWidth="8" />
        <circle
          cx="50" cy="50" r={r} fill="none"
          stroke={color} strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.8s ease", filter: `drop-shadow(0 0 6px ${color}60)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-black tabular-nums" style={{ color: "var(--ink)" }}>{score}</span>
        <span className="text-[9px] font-semibold uppercase tracking-wider" style={{ color: "var(--ink-subtle)" }}>/ 100</span>
      </div>
    </div>
  );
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function PayeeCheck() {
  const { api } = useAuth();
  const { setLastCheck } = useLastCheck();
  const [payload, setPayload] = useState("");
  const [amount, setAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PayeeCheckResult | null>(null);
  const [reported, setReported] = useState(false);

  const [intent, setIntent] = useState<string>("");
  const [message, setMessage] = useState("");
  const [showMessage, setShowMessage] = useState(false);
  const [intents, setIntents] = useState<IntentOption[]>([]);
  const [privacyNote, setPrivacyNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<{ intents: IntentOption[]; message_handling: string }>("/api/payee/intents")
      .then((data) => {
        if (cancelled) return;
        setIntents(data.intents || []);
        setPrivacyNote(data.message_handling || null);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [api]);

  const runCheck = async (value?: string) => {
    const target = (value ?? payload).trim();
    if (!target) {
      setError("Scan a QR code, add a photo of one, or type a UPI ID or phone number.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setReported(false);
    try {
      const data = await api<PayeeCheckResult>("/api/payee/check", {
        method: "POST",
        body: JSON.stringify({
          payload: target,
          amount: amount ? parseFloat(amount) : null,
          intent: intent || null,
          message: message.trim() ? message.trim() : null,
        }),
      });
      setResult(data);
      // Publish it so the assistant can answer questions about THIS verdict.
      setLastCheck(data);
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

  const meta = result ? DECISION_META[result.verdict] ?? DECISION_META.WARN : null;

  // The bonus counts distinct OBSERVATIONS, bounded by the number of families
  // that made them: four facts seen by three families is three streams
  // agreeing, not four. `observed_by` is what says which, so the headline
  // counts families and the chips name the observations.
  const agreeingFacts = result?.agreement?.facts ?? [];
  const agreeingStreams =
    new Set(Object.values(result?.agreement?.observed_by ?? {}).flat()).size ||
    agreeingFacts.length;
  const rep  = result?.reputation;

  return (
    <div className="space-y-8 animate-fade-in" id="payee-check-container">
      {/* Header */}
      <div>
        <h1
          className="text-3xl font-extrabold tracking-tight mb-2"
          style={{ color: "var(--ink)" }}
        >
          Check a{" "}
          <span
            style={{
              background: "linear-gradient(135deg, var(--brand), var(--violet, #7c3aed))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            payee
          </span>
        </h1>
        <p className="max-w-3xl" style={{ color: "var(--ink-muted)" }}>
          Checks who you are about to pay, before the money moves. Every other page here
          scores your own behaviour, which cannot tell that a first payment to a scammer
          is a scam. This looks at the address instead.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* ── Input panel ─────────────────────────────────────────────── */}
        <div
          className="rounded-2xl p-6 h-fit"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            boxShadow: "0 4px 24px rgba(0,0,0,0.06)",
          }}
        >
          <h2 className="text-xl font-bold mb-4" style={{ color: "var(--ink)" }}>Payee details</h2>

          <form onSubmit={(e) => { e.preventDefault(); runCheck(); }} className="space-y-4">
            {/* Scan, photograph, or type. The page used to offer only the
                textarea, labelled "QR contents" - which meant the decoded
                string `upi://pay?pa=...`. Nobody has that: what a person has is
                a code on a counter. QrScanner decodes it on the device and
                hands the payload here, so everything below is unchanged. */}
            <QrScanner
              onPayload={(decoded) => {
                setPayload(decoded);
                setError(null);
                // Deliberately NOT auto-running the check. The payer should see
                // what was read off the code - a swapped sticker is exactly
                // what this page exists to catch - and press the button
                // themselves. Nothing is opened or followed either way.
              }}
              typeTab={
                <div>
                  <label className="block text-sm font-semibold mb-1.5" style={{ color: "var(--ink-muted)" }}>
                    UPI ID, QR contents, or phone number
                  </label>
                  <textarea
                    value={payload}
                    onChange={(e) => setPayload(e.target.value)}
                    rows={3}
                    placeholder="name@bank   ·   upi://pay?pa=...   ·   9876543210"
                    className="w-full px-4 py-3 rounded-xl font-mono text-sm resize-y transition-all duration-150"
                    style={{
                      background: "var(--inset)",
                      border: "1px solid var(--line)",
                      color: "var(--ink)",
                    }}
                    onFocus={(e) => {
                      e.target.style.borderColor = "color-mix(in oklab, var(--brand) 50%, transparent)";
                      e.target.style.boxShadow = "0 0 0 3px color-mix(in oklab, var(--brand) 15%, transparent)";
                    }}
                    onBlur={(e) => {
                      e.target.style.borderColor = "var(--line)";
                      e.target.style.boxShadow = "none";
                    }}
                  />
                </div>
              }
            />

            <div>
              <label className="block text-sm font-semibold mb-1.5" style={{ color: "var(--ink-muted)" }}>
                Amount <span style={{ color: "var(--ink-subtle)", fontWeight: 400 }}>(optional)</span>
              </label>
              <div className="relative">
                <IndianRupee className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--ink-subtle)" }} />
                <input
                  {...rupeeInputProps}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder={`How much are you sending? (max ${describeCap()})`}
                  className="w-full pl-9 pr-4 py-2.5 rounded-xl transition-all duration-150"
                  style={{ background: "var(--inset)", border: "1px solid var(--line)", color: "var(--ink)" }}
                  onFocus={(e) => {
                    e.target.style.borderColor = "color-mix(in oklab, var(--brand) 50%, transparent)";
                    e.target.style.boxShadow = "0 0 0 3px color-mix(in oklab, var(--brand) 15%, transparent)";
                  }}
                  onBlur={(e) => {
                    e.target.style.borderColor = "var(--line)";
                    e.target.style.boxShadow = "none";
                  }}
                />
              </div>
              {amountProblem(amount) && (
                <p className="text-xs mt-1.5" style={{ color: "var(--warn)" }}>
                  {amountProblem(amount)}
                </p>
              )}
            </div>

            {/* Coercion context */}
            {intents.length > 0 && (
              <div className="pt-4 border-t space-y-3" style={{ borderColor: "var(--line)" }}>
                <div>
                  <label className="block text-sm font-semibold mb-1.5" style={{ color: "var(--ink-muted)" }}>
                    Why are you paying? <span style={{ color: "var(--ink-subtle)", fontWeight: 400 }}>(optional)</span>
                  </label>
                  <div className="flex flex-wrap gap-1.5">
                    {intents.map((option) => {
                      const active = intent === option.id;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          onClick={() => setIntent(active ? "" : option.id)}
                          className="px-2.5 py-1.5 rounded-xl border text-xs font-semibold transition-all duration-150 hover:scale-[1.02]"
                          style={
                            active
                              ? {
                                  background: "color-mix(in oklab, var(--brand) 12%, transparent)",
                                  border: "1px solid color-mix(in oklab, var(--brand) 35%, transparent)",
                                  color: "var(--brand)",
                                  boxShadow: "0 2px 8px color-mix(in oklab, var(--brand) 15%, transparent)",
                                }
                              : {
                                  background: "var(--inset)",
                                  border: "1px solid var(--line)",
                                  color: "var(--ink-muted)",
                                }
                          }
                        >
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {!showMessage ? (
                  <button
                    type="button"
                    onClick={() => setShowMessage(true)}
                    className="flex items-center gap-2 text-xs font-medium hover:underline transition-all"
                    style={{ color: "var(--brand)" }}
                  >
                    <MessageSquareWarning className="h-3.5 w-3.5" />
                    Someone messaged you about this? Paste it
                  </button>
                ) : (
                  <div>
                    <label className="block text-sm font-semibold mb-1.5" style={{ color: "var(--ink-muted)" }}>
                      The message that asked you to pay
                    </label>
                    <textarea
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      rows={3}
                      placeholder="Paste the SMS or WhatsApp message here"
                      className="w-full px-3 py-2.5 rounded-xl text-sm resize-y"
                      style={{ background: "var(--inset)", border: "1px solid var(--line)", color: "var(--ink)" }}
                    />
                    {privacyNote && (
                      <p className="mt-1.5 flex gap-1.5 text-[11px] leading-relaxed" style={{ color: "var(--ink-subtle)" }}>
                        <Lock className="h-3 w-3 mt-0.5 shrink-0" />
                        {privacyNote}
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            {error && (
              <div
                className="text-sm rounded-xl p-3"
                style={{
                  background: "color-mix(in oklab, var(--danger) 8%, transparent)",
                  border: "1px solid color-mix(in oklab, var(--danger) 25%, transparent)",
                  color: "var(--danger)",
                }}
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 font-bold text-white rounded-xl transition-all hover:scale-[1.02] hover:opacity-95 disabled:opacity-50 disabled:scale-100 flex items-center justify-center gap-2"
              style={{
                background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
                boxShadow: "0 4px 16px var(--glow-brand, rgba(99,102,241,0.35))",
              }}
            >
              {loading
                ? <Loader2 className="h-5 w-5 animate-spin" />
                : <><ScanLine className="h-4 w-4" /> Check this payee</>
              }
            </button>
          </form>

          {/* Examples */}
          <div className="mt-6 pt-5 border-t" style={{ borderColor: "var(--line)" }}>
            <p className="text-xs font-bold uppercase tracking-wider mb-3" style={{ color: "var(--ink-subtle)" }}>
              Try an example
            </p>
            <div className="space-y-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.label}
                  onClick={() => { setPayload(ex.value); runCheck(ex.value); }}
                  className="w-full text-left px-3 py-2.5 text-sm rounded-xl transition-all hover:scale-[1.01]"
                  style={{
                    background: "var(--inset)",
                    border: "1px solid var(--line)",
                    color: "var(--ink-muted)",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "var(--raised)";
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "color-mix(in oklab, var(--brand) 25%, transparent)";
                    (e.currentTarget as HTMLButtonElement).style.color = "var(--ink)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "var(--inset)";
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--line)";
                    (e.currentTarget as HTMLButtonElement).style.color = "var(--ink-muted)";
                  }}
                >
                  {ex.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ── Result panel ────────────────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-5">
          {result && meta ? (
            <>
              {/* Verdict card */}
              <div
                className="rounded-2xl p-6 flex flex-col md:flex-row md:items-center justify-between gap-6"
                style={{
                  background: meta.gradient,
                  border: `1px solid ${meta.border}`,
                  boxShadow: meta.glow,
                }}
              >
                <div className="flex items-start gap-4">
                  <span
                    className="grid place-items-center h-14 w-14 rounded-2xl shrink-0"
                    style={{
                      background: `color-mix(in oklab, ${meta.text} 12%, var(--surface))`,
                      border: `1px solid ${meta.border}`,
                    }}
                  >
                    <meta.Icon className="h-7 w-7" style={{ color: meta.text }} />
                  </span>
                  <div>
                    <h3 className="text-2xl font-extrabold" style={{ color: "var(--ink)" }}>
                      {DECISION_LABEL[result.verdict] ?? result.verdict}
                    </h3>
                    <p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>{result.headline}</p>
                    {result.payee.vpa && (
                      <p className="text-xs font-mono mt-2" style={{ color: "var(--ink-subtle)" }}>
                        {result.payee.vpa}
                        {result.payee.display_name && ` · shown as "${result.payee.display_name}"`}
                      </p>
                    )}
                  </div>
                </div>

                {/* Circular risk gauge */}
                <div className="text-center shrink-0">
                  <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: "var(--ink-subtle)" }}>
                    Payee risk
                  </div>
                  <RiskGauge score={result.risk_score} color={meta.text} />
                </div>
              </div>

              {/* Agreement bonus */}
              {(result.agreement?.bonus ?? 0) > 0 && (
                <div
                  className="rounded-2xl p-5"
                  style={{
                    background: "color-mix(in oklab, var(--brand) 6%, var(--surface))",
                    border: "1px solid color-mix(in oklab, var(--brand) 20%, transparent)",
                  }}
                >
                  <h3 className="text-sm font-bold mb-1" style={{ color: "var(--ink)" }}>
                    {agreeingStreams} independent check{agreeingStreams === 1 ? "" : "s"} agree
                  </h3>
                  <p className="text-xs leading-relaxed mb-3" style={{ color: "var(--ink-muted)" }}>
                    None of these alone would produce this verdict. They point the same
                    way, and that is what makes it a decision rather than a guess.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {agreeingFacts.map((family) => (
                      <span
                        key={family}
                        className="px-2.5 py-1 rounded-lg text-[11px] font-semibold"
                        style={{
                          background: "color-mix(in oklab, var(--brand) 10%, var(--surface))",
                          border: "1px solid color-mix(in oklab, var(--brand) 25%, transparent)",
                          color: "var(--brand)",
                        }}
                      >
                        {family.replace(/_/g, " ")}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Message pressure */}
              {result.message_pressure?.supplied && result.message_pressure.weak_only && (
                <div
                  className="rounded-xl p-4 text-xs leading-relaxed"
                  style={{ background: "var(--inset)", border: "1px solid var(--line)", color: "var(--ink-muted)" }}
                >
                  The message sounds urgent or official, but genuine bank and biller
                  messages do too. Nothing in it is something a real institution would
                  never do, so it was not counted as pressure on its own.
                </div>
              )}

              {result.message_pressure?.language_note && (
                <div
                  className="rounded-xl p-4 text-xs leading-relaxed"
                  style={{
                    background: "color-mix(in oklab, var(--warn) 6%, transparent)",
                    border: "1px solid color-mix(in oklab, var(--warn) 25%, transparent)",
                    color: "var(--ink-muted)",
                  }}
                >
                  {result.message_pressure.language_note}
                </div>
              )}

              {/* Links */}
              {result.links?.found > 0 && (
                <div
                  className="rounded-2xl p-6"
                  style={{ background: "var(--surface)", border: "1px solid var(--line)" }}
                >
                  <h3 className="text-sm font-bold mb-1" style={{ color: "var(--ink)" }}>
                    {result.links.found === 1 ? "The link in this" : `${result.links.found} links in this`}
                  </h3>
                  <p className="text-xs mb-4" style={{ color: "var(--ink-subtle)" }}>
                    Read from the address only. Nothing here was opened or fetched.
                  </p>
                  <div className="space-y-3">
                    {result.links.links.map((link, i) => (
                      <div
                        key={i}
                        className="rounded-xl p-3"
                        style={{ background: "var(--inset)", border: "1px solid var(--line)" }}
                      >
                        <div className="font-mono text-xs break-all" style={{ color: "var(--ink)" }}>{link.url}</div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
                          <span style={{ color: "var(--ink-subtle)" }}>
                            actually goes to{" "}
                            <span className="font-mono font-semibold" style={{ color: "var(--ink)" }}>{link.registrable}</span>
                          </span>
                          {link.claimed_brand && (
                            <span
                              className="px-1.5 py-0.5 rounded"
                              style={{
                                background: "color-mix(in oklab, var(--warn) 10%, transparent)",
                                border: "1px solid color-mix(in oklab, var(--warn) 25%, transparent)",
                                color: "var(--warn)",
                              }}
                            >
                              claims {link.claimed_brand}
                            </span>
                          )}
                        </div>
                        {link.findings.length > 0 && (
                          <ul className="mt-2.5 space-y-1.5">
                            {link.findings.map((f, j) => (
                              <li key={j} className="text-xs leading-relaxed flex gap-2" style={{ color: "var(--ink-muted)" }}>
                                <span
                                  className="mt-1.5 h-1 w-1 rounded-full shrink-0"
                                  style={{
                                    background: f.severity === "critical" ? "var(--danger)" : f.severity === "high" ? "var(--warn)" : "var(--ink-faint)",
                                  }}
                                />
                                {f.message}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Findings */}
              <div
                className="rounded-2xl p-6"
                style={{ background: "var(--surface)", border: "1px solid var(--line)" }}
              >
                <h3 className="text-lg font-bold mb-4" style={{ color: "var(--ink)" }}>What the check found</h3>
                <ul className="space-y-2">
                  {result.findings.map((f, i) => {
                    const sm = SEVERITY_META[f.severity] ?? SEVERITY_META.info;
                    return (
                      <li
                        key={i}
                        className="text-sm rounded-xl p-3.5"
                        style={{ background: sm.bg, border: `1px solid ${sm.border}`, color: sm.text }}
                      >
                        <span className="uppercase text-[10px] font-bold tracking-wider mr-2 opacity-80">
                          {f.severity}
                        </span>
                        <span style={{ color: "var(--ink-muted)" }}>{f.message}</span>
                      </li>
                    );
                  })}
                  {result.findings.length === 0 && (
                    <li className="text-sm" style={{ color: "var(--ink-muted)" }}>Nothing stood out about this payee.</li>
                  )}
                </ul>
              </div>

              {/* Reputation */}
              <div
                className="rounded-2xl p-6"
                style={{ background: "var(--surface)", border: "1px solid var(--line)" }}
              >
                <h3 className="text-lg font-bold mb-1" style={{ color: "var(--ink)" }}>Payee history</h3>
                <p className="text-xs mb-4" style={{ color: "var(--ink-subtle)" }}>
                  Pooled across everyone using this system. A single wallet app cannot see this.
                </p>

                {rep?.known ? (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {[
                      { Icon: CalendarClock, label: "First seen",       value: rep.age_days !== null ? `${rep.age_days}d ago` : "unknown" },
                      { Icon: Users,         label: "People who paid",  value: String(rep.distinct_payers) },
                      { Icon: Repeat,        label: "Paid > once",      value: String(rep.repeat_payers) },
                      { Icon: Flag,          label: "Reports",          value: String(rep.reports) },
                    ].map(({ Icon, label, value }) => (
                      <div
                        key={label}
                        className="rounded-xl p-3.5"
                        style={{ background: "var(--inset)", border: "1px solid var(--line)" }}
                      >
                        <span
                          className="grid place-items-center h-7 w-7 rounded-lg mb-2"
                          style={{
                            background: "linear-gradient(135deg, color-mix(in oklab, var(--brand) 15%, var(--raised)), color-mix(in oklab, var(--violet, #7c3aed) 10%, var(--raised)))",
                            border: "1px solid color-mix(in oklab, var(--brand) 20%, transparent)",
                          }}
                        >
                          <Icon className="h-3.5 w-3.5" style={{ color: "var(--brand)" }} />
                        </span>
                        <div className="text-lg font-extrabold leading-tight" style={{ color: "var(--ink)" }}>{value}</div>
                        <div className="text-[10px] mt-0.5 font-medium" style={{ color: "var(--ink-subtle)" }}>{label}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div
                    className="flex items-start gap-3 text-sm rounded-xl p-4"
                    style={{ background: "var(--inset)", border: "1px solid var(--line)", color: "var(--ink-muted)" }}
                  >
                    <Info className="h-5 w-5 shrink-0 mt-0.5" style={{ color: "var(--ink-subtle)" }} />
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
                    className="mt-4 flex items-center gap-2 text-sm px-4 py-2.5 rounded-xl transition-all hover:scale-[1.02] disabled:opacity-50 disabled:scale-100"
                    style={{ border: "1px solid var(--line)", color: "var(--ink-muted)", background: "var(--inset)" }}
                    onMouseEnter={(e) => {
                      if (!reported) {
                        (e.currentTarget as HTMLButtonElement).style.background = "var(--raised)";
                        (e.currentTarget as HTMLButtonElement).style.color = "var(--ink)";
                      }
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.background = "var(--inset)";
                      (e.currentTarget as HTMLButtonElement).style.color = "var(--ink-muted)";
                    }}
                  >
                    <Flag className="h-4 w-4" />
                    {reported ? "Reported — thank you" : "Report this payee"}
                  </button>
                )}
              </div>

              {/* Score breakdown */}
              <div
                className="rounded-2xl p-6"
                style={{ background: "var(--surface)", border: "1px solid var(--line)" }}
              >
                <h3 className="text-sm font-bold mb-5" style={{ color: "var(--ink)" }}>Where the score came from</h3>
                <div className="space-y-4">
                  {[
                    ["Address and QR contents",      result.component_scores.address_and_qr],
                    ["Payee history",                result.component_scores.payee_history],
                    ["Amount in context",            result.component_scores.amount_context],
                    ["What you said you were doing", result.component_scores.stated_intent],
                    ["Pressure in the message",      result.component_scores.message_pressure],
                    ["Links in it",                  result.component_scores.link_safety],
                  ].map(([label, value]) => {
                    const pct = Math.min(100, value as number);
                    const barColor = pct >= 70 ? "var(--danger)" : pct >= 40 ? "var(--warn)" : "var(--ok)";
                    return (
                      <div key={label as string}>
                        <div className="flex justify-between text-xs mb-1.5">
                          <span style={{ color: "var(--ink-muted)" }}>{label}</span>
                          <span className="font-mono font-bold" style={{ color: "var(--ink)" }}>{value as number}</span>
                        </div>
                        <div
                          className="h-2 rounded-full overflow-hidden"
                          style={{ background: "var(--raised)" }}
                        >
                          <div
                            className="h-full rounded-full transition-all duration-700"
                            style={{
                              width: `${pct}%`,
                              background: `linear-gradient(to right, ${barColor}, color-mix(in oklab, ${barColor} 75%, var(--violet, #7c3aed)))`,
                              boxShadow: `0 0 6px color-mix(in oklab, ${barColor} 40%, transparent)`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
                {/* `payer_behaviour` is an evidence row; the payer's own
                    assessment is under `detail`. Reading risk_score off the row
                    itself printed "undefined (undefined)", and the label it
                    reached for was the legacy LOW/MEDIUM/HIGH one - the band
                    below is the same vocabulary as the verdict at the top. */}
                {result.payer_behaviour?.detail && (
                  <p className="text-xs mt-4 pt-4 border-t" style={{ borderColor: "var(--line)", color: "var(--ink-subtle)" }}>
                    Against your own history this payment scores{" "}
                    <span className="font-bold" style={{ color: "var(--ink-muted)" }}>
                      {result.payer_behaviour.detail.risk_score}
                      {result.payer_behaviour.detail.band ? ` (${result.payer_behaviour.detail.band})` : ""}
                    </span>.
                  </p>
                )}
              </div>
            </>
          ) : (
            /* Empty state */
            <div
              className="rounded-2xl p-12 text-center h-full flex flex-col justify-center items-center"
              style={{ background: "color-mix(in oklab, var(--surface) 50%, transparent)", border: "1px solid var(--line)" }}
            >
              {/* Animated scan icon */}
              <div className="relative mb-6">
                <div
                  className="h-20 w-20 rounded-2xl flex items-center justify-center"
                  style={{
                    background: "linear-gradient(135deg, color-mix(in oklab, var(--brand) 10%, var(--raised)), color-mix(in oklab, var(--violet, #7c3aed) 8%, var(--raised)))",
                    border: "1px solid color-mix(in oklab, var(--brand) 20%, transparent)",
                    boxShadow: "0 0 30px color-mix(in oklab, var(--brand) 15%, transparent)",
                  }}
                >
                  <ScanLine className="h-9 w-9" style={{ color: "var(--brand)" }} />
                </div>
                {/* Orbiting ring */}
                <div
                  className="absolute inset-0 rounded-2xl"
                  style={{
                    border: "1px solid color-mix(in oklab, var(--brand) 15%, transparent)",
                    transform: "scale(1.15)",
                    animation: "pulse-glow 3s ease-in-out infinite",
                  }}
                />
              </div>
              <h3 className="text-lg font-bold mb-1.5" style={{ color: "var(--ink)" }}>Check before you pay</h3>
              <p className="max-w-md text-sm" style={{ color: "var(--ink-muted)" }}>
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
