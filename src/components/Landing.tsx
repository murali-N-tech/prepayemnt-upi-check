import React, { useState } from "react";
import {
  ArrowRight,
  BadgeCheck,
  Braces,
  FileText,
  GitBranch,
  QrCode,
  ScanLine,
  ShieldAlert,
  Users,
  TrendingUp,
  Zap,
  Shield,
} from "lucide-react";
import { LogoMark, Wordmark } from "./ui/Logo";
import { ThemeToggle } from "./ui/ThemeToggle";

interface LandingProps {
  onSignIn: () => void;
  onCreateAccount: () => void;
}

const EXAMPLES = [
  {
    key: "typosquat",
    tab: "Look-alike ID",
    icon: ScanLine,
    input: "swiggy-refund@okaxls",
    verdict: "BLOCK",
    tone: "danger" as const,
    score: 82,
    findings: [
      ["critical", "@okaxls is not a handle any UPI provider uses — it is @okaxis with a lowercase L"],
      ["high", "Uses a known brand name together with a refund lure"],
      ["warn", "First time you would pay this address"],
    ],
  },
  {
    key: "qr",
    tab: "Tampered QR",
    icon: QrCode,
    input: "upi://pay?pa=rk4482@ybl&pn=Bharat%20Petroleum&am=2500",
    verdict: "STEP UP",
    tone: "warn" as const,
    score: 58,
    findings: [
      ["high", "The name in the QR does not match the account it pays — the signature of a sticker placed over the real code"],
      ["warn", "The payee has been paid by 41 people, 39 of them exactly once"],
      ["info", "Amount is 8× your typical payment at a fuel station"],
    ],
  },
  {
    key: "ring",
    tab: "Collection account",
    icon: Users,
    input: "9xxxxxxxx1@upi",
    verdict: "BLOCK",
    tone: "danger" as const,
    score: 74,
    findings: [
      ["critical", "Shares 6 one-shot payers with 3 other accounts opened the same week"],
      ["high", "Money in, nothing out to merchants — a collection pattern, not a shop"],
      ["warn", "Payee is a phone number, which resolves to whoever holds it today"],
    ],
  },
];

const SEVERITY: Record<string, { dot: string; label: string }> = {
  critical: { dot: "bg-danger", label: "text-danger" },
  high:     { dot: "bg-warn",   label: "text-warn" },
  warn:     { dot: "bg-ink-faint", label: "text-ink-subtle" },
  info:     { dot: "bg-ink-faint", label: "text-ink-subtle" },
};

/* ─────────────────────────────────────────────────────────────────────────── */

const LandingHeader: React.FC<LandingProps> = ({ onSignIn, onCreateAccount }) => (
  <header
    className="sticky top-0 z-30 border-b"
    style={{
      background: "color-mix(in oklab, var(--canvas) 85%, transparent)",
      backdropFilter: "blur(20px) saturate(1.4)",
      borderColor: "color-mix(in oklab, var(--line) 70%, transparent)",
    }}
  >
    <div className="mx-auto max-w-6xl px-4 sm:px-6 h-16 flex items-center gap-4">
      <Wordmark subtitle="Behavioural risk" />
      <nav className="hidden md:flex items-center gap-1 ml-6">
        {[
          ["Why", "#why"],
          ["How it works", "#how"],
          ["What it catches", "#catches"],
          ["Evidence", "#evidence"],
        ].map(([label, href]) => (
          <a
            key={href}
            href={href}
            className="px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150"
            style={{ color: "var(--ink-muted)" }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.color = "var(--ink)";
              (e.currentTarget as HTMLAnchorElement).style.background = "var(--raised)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.color = "var(--ink-muted)";
              (e.currentTarget as HTMLAnchorElement).style.background = "transparent";
            }}
          >
            {label}
          </a>
        ))}
      </nav>
      <div className="flex-1" />
      <ThemeToggle compact />
      <button
        onClick={onSignIn}
        className="hidden sm:block px-3 py-2 rounded-lg text-sm font-medium transition-all hover:scale-[1.02]"
        style={{ color: "var(--ink-muted)", background: "var(--raised)" }}
      >
        Sign in
      </button>
      <button
        onClick={onCreateAccount}
        className="px-4 py-2 rounded-xl text-sm font-bold text-white transition-all hover:scale-[1.03] hover:opacity-95"
        style={{
          background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
          boxShadow: "0 4px 16px var(--glow-brand, rgba(99,102,241,0.35))",
        }}
      >
        Get started
      </button>
    </div>
  </header>
);

/* ── Hero ─────────────────────────────────────────────────────────────────── */

const Hero: React.FC<LandingProps> = ({ onCreateAccount, onSignIn }) => (
  <section className="relative overflow-hidden">
    {/* Ambient blobs */}
    <div
      className="blob blob-brand"
      style={{
        width: 600, height: 600,
        top: -200, left: -100,
        animationDelay: "0s",
        animationDuration: "14s",
      }}
    />
    <div
      className="blob blob-violet"
      style={{
        width: 500, height: 500,
        top: -100, right: -150,
        animationDelay: "4s",
        animationDuration: "18s",
      }}
    />
    <div
      className="blob blob-pink"
      style={{
        width: 350, height: 350,
        bottom: -100, left: "40%",
        animationDelay: "8s",
        animationDuration: "16s",
      }}
    />

    {/* Grid overlay */}
    <div className="absolute inset-0 hero-grid pointer-events-none" aria-hidden="true" />

    <div className="relative mx-auto max-w-6xl px-4 sm:px-6 pt-20 pb-20 md:pt-32 md:pb-28">
      <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-14 items-center">
        {/* Left — copy */}
        <div className="animate-rise">
          <span
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-semibold mb-6"
            style={{
              background: "color-mix(in oklab, var(--brand) 10%, var(--surface))",
              border: "1px solid color-mix(in oklab, var(--brand) 25%, transparent)",
              color: "var(--brand)",
            }}
          >
            <Zap className="h-3.5 w-3.5" />
            Pre-payment, not post-mortem
          </span>

          <h1
            className="text-4xl sm:text-5xl lg:text-[3.6rem] font-extrabold tracking-tight leading-[1.04]"
            style={{ color: "var(--ink)" }}
          >
            Check who you are paying
            <span
              className="block mt-1"
              style={{
                background: "linear-gradient(135deg, var(--brand) 0%, var(--violet, #7c3aed) 50%, var(--pink, #db2777) 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              before the money leaves.
            </span>
          </h1>

          <p
            className="mt-6 text-lg leading-relaxed max-w-xl"
            style={{ color: "var(--ink-muted)" }}
          >
            UPI is instant and irreversible. Once you approve the payment, no
            fraud model can help you. This one runs on the payee — the UPI ID,
            the QR code, the account's history — in the seconds before you tap Pay.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <button
              onClick={onCreateAccount}
              className="inline-flex items-center gap-2 px-6 py-3.5 rounded-xl text-sm font-bold text-white transition-all hover:scale-[1.03]"
              style={{
                background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
                boxShadow: "0 6px 24px var(--glow-brand, rgba(99,102,241,0.4))",
              }}
            >
              Check a payee
              <ArrowRight className="h-4 w-4" />
            </button>
            <button
              onClick={onSignIn}
              className="px-6 py-3.5 rounded-xl text-sm font-semibold transition-all hover:scale-[1.02]"
              style={{
                color: "var(--ink)",
                background: "color-mix(in oklab, var(--surface) 90%, transparent)",
                border: "1px solid var(--line-strong)",
                backdropFilter: "blur(8px)",
              }}
            >
              I have an account
            </button>
          </div>

          <p className="mt-5 text-xs max-w-md leading-relaxed" style={{ color: "var(--ink-subtle)" }}>
            Your UPI ID is your login. It is checked for format and for a real
            bank handle; nothing claims the account is verified unless a
            payment provider actually confirms it.
          </p>
        </div>

        {/* Right — product illustration */}
        <div className="animate-rise" style={{ animationDelay: "120ms" }}>
          <div
            className="rounded-2xl overflow-hidden"
            style={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              boxShadow:
                "0 4px 6px rgba(0,0,0,0.07), 0 20px 60px -10px rgba(0,0,0,0.15), 0 0 0 1px color-mix(in oklab, var(--brand) 12%, transparent)",
            }}
          >
            {/* Card title bar */}
            <div
              className="flex items-center gap-2 px-4 py-3 border-b"
              style={{
                background: "linear-gradient(135deg, color-mix(in oklab, var(--brand) 8%, var(--raised)), color-mix(in oklab, var(--violet, #7c3aed) 6%, var(--raised)))",
                borderColor: "var(--line)",
              }}
            >
              <LogoMark className="h-4 w-4 text-brand" />
              <span
                className="text-xs font-bold"
                style={{ color: "var(--ink)" }}
              >
                Payee check
              </span>
              <span
                className="ml-auto text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-md"
                style={{
                  color: "var(--ink-subtle)",
                  background: "var(--raised)",
                  border: "1px solid var(--line)",
                }}
              >
                illustration
              </span>
            </div>

            <div className="p-5 space-y-4">
              {/* Input field */}
              <div
                className="rounded-lg px-3 py-2.5 font-mono text-sm break-all"
                style={{
                  background: "var(--inset)",
                  border: "1px solid var(--line)",
                  color: "var(--ink)",
                }}
              >
                swiggy-refund@okaxls
              </div>

              {/* Verdict row */}
              <div className="flex items-center gap-3">
                <span
                  className="px-2.5 py-1 rounded-lg text-xs font-bold tracking-wide"
                  style={{
                    background: "color-mix(in oklab, var(--danger) 10%, transparent)",
                    border: "1px solid color-mix(in oklab, var(--danger) 25%, transparent)",
                    color: "var(--danger)",
                  }}
                >
                  BLOCK
                </span>
                <div
                  className="flex-1 h-1.5 rounded-full overflow-hidden"
                  style={{ background: "var(--raised)" }}
                >
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: "82%",
                      background: "linear-gradient(to right, var(--danger), color-mix(in oklab, var(--danger) 70%, var(--pink, #db2777)))",
                    }}
                  />
                </div>
                <span className="text-sm font-bold tabular-nums" style={{ color: "var(--ink)" }}>82</span>
              </div>

              {/* Findings */}
              <ul className="space-y-2.5">
                {EXAMPLES[0].findings.map(([severity, text]) => (
                  <li key={text} className="flex gap-2.5 text-sm leading-snug">
                    <span
                      className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${SEVERITY[severity]?.dot ?? "bg-ink-faint"}`}
                    />
                    <span style={{ color: "var(--ink-muted)" }}>
                      <span
                        className={`font-bold uppercase text-[10px] tracking-wider mr-1.5 ${SEVERITY[severity]?.label ?? "text-ink-subtle"}`}
                      >
                        {severity}
                      </span>
                      {text}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
);

/* ── Stats bar ────────────────────────────────────────────────────────────── */

const Stats: React.FC = () => (
  <div
    className="border-y"
    style={{
      borderColor: "var(--line)",
      background: "linear-gradient(135deg, color-mix(in oklab, var(--brand) 5%, var(--surface)), color-mix(in oklab, var(--violet, #7c3aed) 4%, var(--surface)))",
    }}
  >
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-8">
      <div className="grid grid-cols-3 gap-6 text-center">
        {[
          { icon: TrendingUp, value: "0.98", label: "ROC-AUC score", sub: "Overall separation" },
          { icon: Shield,     value: "68.4%",label: "Recall @ 1% FP", sub: "Caught within budget" },
          { icon: Zap,        value: "<500ms",label: "Check latency", sub: "Before you tap Pay" },
        ].map(({ icon: Icon, value, label, sub }) => (
          <div key={label} className="space-y-1">
            <Icon
              className="h-5 w-5 mx-auto mb-2"
              style={{ color: "var(--brand)" }}
            />
            <div
              className="text-2xl sm:text-3xl font-extrabold"
              style={{
                background: "linear-gradient(135deg, var(--brand), var(--violet, #7c3aed))",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              {value}
            </div>
            <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{label}</div>
            <div className="text-xs" style={{ color: "var(--ink-subtle)" }}>{sub}</div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

/* ── Why ──────────────────────────────────────────────────────────────────── */

const Why: React.FC = () => (
  <section id="why" className="scroll-mt-20 border-t" style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
      <div className="max-w-2xl">
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          Most fraud systems score the wrong side, too late
        </h2>
        <p className="mt-4 leading-relaxed" style={{ color: "var(--ink-muted)" }}>
          A classifier watching your spending can tell you that a payment was
          unusual. It cannot tell you that the person on the other end has been
          paid once each by forty strangers this week. In UPI's dominant fraud
          patterns the payer behaves completely normally — they were persuaded.
          The evidence is on the payee.
        </p>
      </div>

      <div className="mt-10 grid sm:grid-cols-3 gap-4">
        {[
          {
            icon: ShieldAlert,
            title: "Irreversible by design",
            body: "UPI settles in seconds. A check that runs after the transfer is an incident report, not a defence.",
          },
          {
            icon: Users,
            title: "The victim looks fine",
            body: "In social-engineering fraud the payer authorises willingly. Their amount, device and hour are all ordinary.",
          },
          {
            icon: GitBranch,
            title: "The receiver does not",
            body: "Mule accounts collect from many one-shot payers and pay nobody. That shape is visible before you send.",
          },
        ].map(({ icon: Icon, title, body }) => (
          <div
            key={title}
            className="rounded-2xl p-5 transition-all duration-200 hover:-translate-y-1"
            style={{
              background: "var(--canvas)",
              border: "1px solid var(--line)",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLDivElement).style.boxShadow =
                "0 8px 32px color-mix(in oklab, var(--brand) 12%, transparent)";
              (e.currentTarget as HTMLDivElement).style.borderColor =
                "color-mix(in oklab, var(--brand) 30%, transparent)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLDivElement).style.boxShadow = "none";
              (e.currentTarget as HTMLDivElement).style.borderColor = "var(--line)";
            }}
          >
            <span
              className="inline-grid place-items-center h-9 w-9 rounded-xl mb-3"
              style={{
                background: "linear-gradient(135deg, color-mix(in oklab, var(--brand) 15%, var(--raised)), color-mix(in oklab, var(--violet, #7c3aed) 10%, var(--raised)))",
                border: "1px solid color-mix(in oklab, var(--brand) 20%, transparent)",
              }}
            >
              <Icon className="h-5 w-5" style={{ color: "var(--brand)" }} />
            </span>
            <h3 className="font-semibold" style={{ color: "var(--ink)" }}>{title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>{body}</p>
          </div>
        ))}
      </div>
    </div>
  </section>
);

/* ── How ──────────────────────────────────────────────────────────────────── */

const How: React.FC = () => (
  <section id="how" className="scroll-mt-20 border-t" style={{ borderColor: "var(--line)" }}>
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
      <h2 className="text-2xl md:text-3xl font-bold tracking-tight" style={{ color: "var(--ink)" }}>How it works</h2>
      <p className="mt-3 max-w-2xl" style={{ color: "var(--ink-muted)" }}>
        Four checks run against every payee, and the strongest signal decides.
      </p>

      <ol className="mt-10 grid md:grid-cols-4 gap-4">
        {[
          {
            n: "01",
            icon: ScanLine,
            title: "Read the address",
            body: "Structure, a real PSP handle, brand names paired with lure words, and confusables — the l/1 and o/0 swaps that make a fake ID look right.",
          },
          {
            n: "02",
            icon: QrCode,
            title: "Read the QR",
            body: "A UPI deep link that carries a name not matching the account it pays is the signature of a sticker over the real code.",
          },
          {
            n: "03",
            icon: GitBranch,
            title: "Read the graph",
            body: "Fan-in from one-shot payers, accounts sharing payers with each other, and reports from people who paid before you.",
          },
          {
            n: "04",
            icon: Braces,
            title: "Read your history",
            body: "Your own statement sets the baseline: typical amount, usual hours, payees you already know. New and unusual together is what matters.",
          },
        ].map(({ n, icon: Icon, title, body }, idx) => (
          <li
            key={n}
            className="relative rounded-2xl p-5 transition-all duration-200 hover:-translate-y-1"
            style={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              animationDelay: `${idx * 80}ms`,
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLLIElement).style.boxShadow =
                "0 8px 32px color-mix(in oklab, var(--brand) 12%, transparent)";
              (e.currentTarget as HTMLLIElement).style.borderColor =
                "color-mix(in oklab, var(--brand) 30%, transparent)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLLIElement).style.boxShadow = "none";
              (e.currentTarget as HTMLLIElement).style.borderColor = "var(--line)";
            }}
          >
            <div className="flex items-center justify-between mb-3">
              <span
                className="grid place-items-center h-9 w-9 rounded-xl"
                style={{
                  background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
                  boxShadow: "0 4px 12px var(--glow-brand, rgba(99,102,241,0.3))",
                }}
              >
                <Icon className="h-4 w-4 text-white" />
              </span>
              <span
                className="font-mono text-xs font-bold px-2 py-0.5 rounded-lg"
                style={{
                  color: "var(--ink-faint)",
                  background: "var(--raised)",
                }}
              >
                {n}
              </span>
            </div>
            <h3 className="font-semibold" style={{ color: "var(--ink)" }}>{title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>{body}</p>
          </li>
        ))}
      </ol>

      {/* Verdict legend */}
      <div
        className="mt-8 rounded-2xl p-5 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm"
        style={{
          background: "linear-gradient(135deg, color-mix(in oklab, var(--brand) 6%, var(--raised)), color-mix(in oklab, var(--violet, #7c3aed) 4%, var(--raised)))",
          border: "1px solid color-mix(in oklab, var(--brand) 15%, transparent)",
        }}
      >
        <span className="font-semibold" style={{ color: "var(--ink)" }}>The verdict:</span>
        {[
          ["APPROVE", "var(--ok)"],
          ["WARN",    "var(--ink-muted)"],
          ["STEP UP", "var(--warn)"],
          ["BLOCK",   "var(--danger)"],
        ].map(([label, color], i) => (
          <React.Fragment key={label}>
            {i > 0 && <span style={{ color: "var(--ink-faint)" }}>→</span>}
            <span className="font-mono font-bold" style={{ color }}>{label}</span>
          </React.Fragment>
        ))}
        <span className="w-full sm:w-auto sm:ml-2" style={{ color: "var(--ink-muted)" }}>
          Every verdict comes with the findings that produced it, in words.
        </span>
      </div>
    </div>
  </section>
);

/* ── Catches ──────────────────────────────────────────────────────────────── */

const Catches: React.FC = () => {
  const [active, setActive] = useState(EXAMPLES[0].key);
  const example = EXAMPLES.find((e) => e.key === active) ?? EXAMPLES[0];

  const toneColor = example.tone === "danger" ? "var(--danger)" : "var(--warn)";
  const toneGlow = example.tone === "danger" ? "var(--glow-danger, rgba(220,38,38,0.3))" : "var(--glow-warn, rgba(180,83,9,0.3))";
  const toneBg = example.tone === "danger"
    ? "color-mix(in oklab, var(--danger) 8%, transparent)"
    : "color-mix(in oklab, var(--warn) 8%, transparent)";

  return (
    <section id="catches" className="scroll-mt-20 border-t" style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight" style={{ color: "var(--ink)" }}>
          What it catches
        </h2>
        <p className="mt-3 max-w-2xl" style={{ color: "var(--ink-muted)" }}>
          Three patterns, written out as the check would report them. These are
          worked examples, not live results.
        </p>

        <div className="mt-8 grid lg:grid-cols-[16rem_1fr] gap-6">
          {/* Tab list */}
          <div
            role="tablist"
            aria-label="Fraud patterns"
            className="flex lg:flex-col gap-2 overflow-x-auto lg:overflow-visible pb-1"
          >
            {EXAMPLES.map((item) => {
              const Icon = item.icon;
              const isActive = item.key === active;
              return (
                <button
                  key={item.key}
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setActive(item.key)}
                  className="flex items-center gap-3 px-4 py-3 rounded-xl text-left shrink-0 transition-all duration-200 hover:scale-[1.02]"
                  style={
                    isActive
                      ? {
                          background:
                            "linear-gradient(135deg, color-mix(in oklab, var(--brand) 12%, transparent), color-mix(in oklab, var(--violet, #7c3aed) 8%, transparent))",
                          border: "1px solid color-mix(in oklab, var(--brand) 28%, transparent)",
                          color: "var(--ink)",
                          boxShadow: "0 4px 16px color-mix(in oklab, var(--brand) 15%, transparent)",
                        }
                      : {
                          background: "var(--canvas)",
                          border: "1px solid var(--line)",
                          color: "var(--ink-muted)",
                        }
                  }
                >
                  <span
                    className="grid place-items-center h-7 w-7 rounded-lg shrink-0"
                    style={
                      isActive
                        ? {
                            background:
                              "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
                          }
                        : { background: "var(--raised)" }
                    }
                  >
                    <Icon
                      className="h-3.5 w-3.5"
                      style={{ color: isActive ? "#fff" : "var(--ink-subtle)" }}
                    />
                  </span>
                  <span className="text-sm font-semibold whitespace-nowrap">{item.tab}</span>
                </button>
              );
            })}
          </div>

          {/* Detail panel */}
          <div
            className="rounded-2xl p-5 sm:p-6"
            style={{ background: "var(--canvas)", border: "1px solid var(--line)" }}
          >
            <div
              className="text-[10px] font-bold uppercase tracking-[0.14em]"
              style={{ color: "var(--ink-subtle)" }}
            >
              Payee
            </div>
            <div className="mt-2 font-mono text-sm break-all" style={{ color: "var(--ink)" }}>
              {example.input}
            </div>

            <div className="mt-5 flex items-center gap-3">
              <span
                className="px-2.5 py-1 rounded-lg text-xs font-bold tracking-wide"
                style={{ background: toneBg, border: `1px solid ${toneColor}40`, color: toneColor }}
              >
                {example.verdict}
              </span>
              <div
                className="flex-1 h-1.5 rounded-full overflow-hidden"
                style={{ background: "var(--raised)" }}
              >
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${example.score}%`,
                    background: `linear-gradient(to right, ${toneColor}, color-mix(in oklab, ${toneColor} 70%, var(--pink, #db2777)))`,
                    boxShadow: `0 0 8px ${toneGlow}`,
                  }}
                />
              </div>
              <span className="text-sm font-bold tabular-nums" style={{ color: "var(--ink)" }}>
                {example.score}
              </span>
            </div>

            <ul className="mt-5 space-y-3">
              {example.findings.map(([severity, text]) => (
                <li key={text} className="flex gap-3 text-sm leading-relaxed">
                  <span
                    className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${SEVERITY[severity]?.dot ?? "bg-ink-faint"}`}
                  />
                  <span style={{ color: "var(--ink-muted)" }}>
                    <span
                      className={`font-bold uppercase text-[10px] tracking-wider mr-2 ${SEVERITY[severity]?.label ?? "text-ink-subtle"}`}
                    >
                      {severity}
                    </span>
                    {text}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
};

/* ── Evidence ──────────────────────────────────────────────────────────────── */

const Evidence: React.FC = () => (
  <section id="evidence" className="scroll-mt-20 border-t" style={{ borderColor: "var(--line)" }}>
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
      <div className="grid lg:grid-cols-[1fr_1.1fr] gap-10 items-start">
        <div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight" style={{ color: "var(--ink)" }}>
            Measured, and honest about it
          </h2>
          <p className="mt-4 leading-relaxed" style={{ color: "var(--ink-muted)" }}>
            Fraud is rare, so accuracy is a meaningless score. These are the
            numbers that actually say something: how well the model ranks fraud
            above legitimate payments, and how much it catches at a realistic
            alert rate.
          </p>
          <p className="mt-4 text-sm leading-relaxed" style={{ color: "var(--ink-subtle)" }}>
            The classifier is trained on a simulator, so these figures
            demonstrate the method rather than field performance.
          </p>
        </div>

        <div
          className="rounded-2xl overflow-hidden"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
          }}
        >
          <div className="grid grid-cols-[1fr_auto_auto] text-xs">
            {/* Header */}
            <div
              className="px-5 py-3 font-bold text-ink uppercase tracking-wider text-[10px] border-b"
              style={{ borderColor: "var(--line)", color: "var(--ink-subtle)" }}
            >
              Metric
            </div>
            <div
              className="px-4 py-3 font-bold uppercase tracking-wider text-[10px] border-b text-right"
              style={{ borderColor: "var(--line)", color: "var(--ink)" }}
            >
              This model
            </div>
            <div
              className="px-5 py-3 font-bold uppercase tracking-wider text-[10px] border-b text-right"
              style={{ borderColor: "var(--line)", color: "var(--ink-subtle)" }}
            >
              Baseline
            </div>

            {[
              ["PR-AUC", "0.62", "0.18", "Ranking quality where fraud is rare"],
              ["ROC-AUC", "0.98", "0.95", "Overall separation"],
              ["Recall at 1% false positives", "68.4%", "23.9%", "Caught, within a realistic alert budget"],
            ].map(([label, mine, base, note]) => (
              <React.Fragment key={label}>
                <div className="px-5 py-4 border-b" style={{ borderColor: "var(--line)" }}>
                  <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{label}</div>
                  <div className="text-[11px] mt-0.5" style={{ color: "var(--ink-subtle)" }}>{note}</div>
                </div>
                <div className="px-4 py-4 border-b text-right" style={{ borderColor: "var(--line)" }}>
                  <span
                    className="text-xl font-extrabold tabular-nums"
                    style={{
                      background: "linear-gradient(135deg, var(--brand), var(--violet, #7c3aed))",
                      WebkitBackgroundClip: "text",
                      WebkitTextFillColor: "transparent",
                      backgroundClip: "text",
                    }}
                  >
                    {mine}
                  </span>
                </div>
                <div className="px-5 py-4 border-b text-right" style={{ borderColor: "var(--line)" }}>
                  <span className="text-sm tabular-nums" style={{ color: "var(--ink-subtle)" }}>{base}</span>
                </div>
              </React.Fragment>
            ))}
          </div>
          <div
            className="px-5 py-3 text-[11px] border-t"
            style={{
              background: "var(--raised)",
              borderColor: "var(--line)",
              color: "var(--ink-subtle)",
            }}
          >
            Baseline is logistic regression on the same features. An ablation
            shows the payee-side checks carry 22.6% of social-engineering
            recall on their own, and 58.4% together with the payer side.
          </div>
        </div>
      </div>
    </div>
  </section>
);

/* ── CTA ──────────────────────────────────────────────────────────────────── */

const Cta: React.FC<LandingProps> = ({ onCreateAccount }) => (
  <section className="relative overflow-hidden border-t" style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
    {/* Gradient background */}
    <div
      className="absolute inset-0 pointer-events-none"
      style={{
        background:
          "radial-gradient(ellipse 80% 60% at 50% 100%, color-mix(in oklab, var(--brand) 8%, transparent), transparent)",
      }}
    />
    <div className="relative mx-auto max-w-6xl px-4 sm:px-6 py-20 md:py-24 text-center">
      <h2
        className="text-3xl md:text-4xl font-extrabold tracking-tight"
        style={{ color: "var(--ink)" }}
      >
        Start with{" "}
        <span
          style={{
            background: "linear-gradient(135deg, var(--brand) 0%, var(--violet, #7c3aed) 50%, var(--pink, #db2777) 100%)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}
        >
          one payee
        </span>
      </h2>
      <p className="mt-4 max-w-xl mx-auto leading-relaxed" style={{ color: "var(--ink-muted)" }}>
        Sign up with your UPI ID, paste an address or a scanned QR, and read
        the findings. Upload a statement afterwards and the check starts using
        your own history too.
      </p>
      <button
        onClick={onCreateAccount}
        className="mt-8 inline-flex items-center gap-2 px-8 py-4 rounded-2xl text-sm font-bold text-white transition-all hover:scale-[1.04]"
        style={{
          background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
          boxShadow: "0 8px 32px var(--glow-brand, rgba(99,102,241,0.4)), 0 2px 8px rgba(0,0,0,0.15)",
        }}
      >
        Create an account
        <ArrowRight className="h-4 w-4" />
      </button>
      <p
        className="mt-5 text-xs flex items-center justify-center gap-1.5"
        style={{ color: "var(--ink-subtle)" }}
      >
        <BadgeCheck className="h-3.5 w-3.5 shrink-0" />
        Nothing here moves money. The system reads and scores; it never pays.
      </p>
    </div>
  </section>
);

/* ── Footer ───────────────────────────────────────────────────────────────── */

const Footer: React.FC = () => (
  <footer className="border-t" style={{ borderColor: "var(--line)" }}>
    <div
      className="mx-auto max-w-6xl px-4 sm:px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4"
    >
      <div className="flex items-center gap-2 text-sm" style={{ color: "var(--ink-subtle)" }}>
        <LogoMark className="h-4 w-4" style={{ color: "var(--brand)" } as any} />
        <span>Edge AI UPI Behavioural Risk Intelligence System</span>
      </div>
      <div className="flex items-center gap-4 text-xs" style={{ color: "var(--ink-subtle)" }}>
        <span className="inline-flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5" />
          Final-year project · not a licensed payment service
        </span>
      </div>
    </div>
  </footer>
);

export const Landing: React.FC<LandingProps> = (props) => (
  <div className="min-h-screen font-sans" style={{ background: "var(--canvas)", color: "var(--ink)" }}>
    <LandingHeader {...props} />
    <main>
      <Hero {...props} />
      <Stats />
      <Why />
      <How />
      <Catches />
      <Evidence />
      <Cta {...props} />
    </main>
    <Footer />
  </div>
);

export default Landing;
