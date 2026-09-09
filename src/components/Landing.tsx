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
} from "lucide-react";
import { LogoMark, Wordmark } from "./ui/Logo";
import { ThemeToggle } from "./ui/ThemeToggle";

interface LandingProps {
  onSignIn: () => void;
  onCreateAccount: () => void;
}

/* ── The three example verdicts ──────────────────────────────────────────────
   These are illustrations of what the checks look for, written out by hand.
   They are not live results, and the copy says so, because a landing page
   that implies a real check ran is the same class of dishonesty the product
   exists to prevent. */

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

const TONE = {
  danger: {
    chip: "bg-danger/10 text-danger border-danger/25",
    bar: "bg-danger",
  },
  warn: {
    chip: "bg-warn/10 text-warn border-warn/25",
    bar: "bg-warn",
  },
};

const SEVERITY: Record<string, string> = {
  critical: "text-danger",
  high: "text-warn",
  warn: "text-ink-muted",
  info: "text-ink-subtle",
};

/* ─────────────────────────────────────────────────────────────────────────── */

const LandingHeader: React.FC<LandingProps> = ({ onSignIn, onCreateAccount }) => (
  <header className="sticky top-0 z-30 border-b border-line bg-canvas/80 backdrop-blur-md">
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
            className="px-3 py-2 rounded-lg text-sm text-ink-muted hover:text-ink hover:bg-raised transition"
          >
            {label}
          </a>
        ))}
      </nav>
      <div className="flex-1" />
      <ThemeToggle compact />
      <button
        onClick={onSignIn}
        className="hidden sm:block px-3 py-2 rounded-lg text-sm font-medium text-ink-muted hover:text-ink hover:bg-raised transition whitespace-nowrap"
      >
        Sign in
      </button>
      <button
        onClick={onCreateAccount}
        className="px-3 sm:px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-ink hover:opacity-90 transition shadow-card whitespace-nowrap"
      >
        Get started
      </button>
    </div>
  </header>
);

const Hero: React.FC<LandingProps> = ({ onCreateAccount, onSignIn }) => (
  <section className="relative overflow-hidden">
    <div className="absolute inset-0 hero-grid pointer-events-none" aria-hidden="true" />
    <div className="relative mx-auto max-w-6xl px-4 sm:px-6 pt-20 pb-16 md:pt-28 md:pb-24">
      <div className="grid lg:grid-cols-[1.05fr_0.95fr] gap-12 items-center">
        <div className="animate-rise">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-line bg-surface text-xs font-medium text-ink-muted shadow-card">
            <span className="h-1.5 w-1.5 rounded-full bg-brand" />
            Pre-payment, not post-mortem
          </span>

          <h1 className="mt-6 text-4xl sm:text-5xl lg:text-[3.4rem] font-extrabold tracking-tight text-ink leading-[1.05]">
            Check who you are paying
            <span className="block text-brand">before the money leaves.</span>
          </h1>

          <p className="mt-6 text-lg leading-relaxed text-ink-muted max-w-xl">
            UPI is instant and irreversible. Once you approve the payment, no
            fraud model can help you. This one runs on the payee — the UPI ID,
            the QR code, the account's history with other payers — in the
            seconds before you tap Pay.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <button
              onClick={onCreateAccount}
              className="inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold text-white bg-brand-ink hover:opacity-90 transition shadow-lift"
            >
              Check a payee
              <ArrowRight className="h-4 w-4" />
            </button>
            <button
              onClick={onSignIn}
              className="px-5 py-3 rounded-xl text-sm font-semibold text-ink border border-line-strong bg-surface hover:bg-raised transition"
            >
              I have an account
            </button>
          </div>

          <p className="mt-5 text-xs text-ink-subtle max-w-md leading-relaxed">
            Your UPI ID is your login. It is checked for format and for a real
            bank handle; nothing claims the account is verified unless a
            payment provider actually confirms it.
          </p>
        </div>

        {/* The product, shown rather than described. */}
        <div className="animate-rise [animation-delay:120ms]">
          <div className="rounded-2xl border border-line bg-surface shadow-lift overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-line bg-raised">
              <LogoMark className="h-4 w-4 text-brand" />
              <span className="text-xs font-semibold text-ink">Payee check</span>
              <span className="ml-auto text-[10px] font-mono uppercase tracking-wider text-ink-subtle">
                illustration
              </span>
            </div>
            <div className="p-5 space-y-4">
              <div className="rounded-lg border border-line bg-inset px-3 py-2.5 font-mono text-sm text-ink break-all">
                swiggy-refund@okaxls
              </div>

              <div className="flex items-center gap-3">
                <span className={`px-2.5 py-1 rounded-md border text-xs font-bold tracking-wide ${TONE.danger.chip}`}>
                  BLOCK
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-raised overflow-hidden">
                  <div className={`h-full rounded-full ${TONE.danger.bar}`} style={{ width: "82%" }} />
                </div>
                <span className="text-sm font-bold text-ink tabular-nums">82</span>
              </div>

              <ul className="space-y-2.5">
                {EXAMPLES[0].findings.map(([severity, text]) => (
                  <li key={text} className="flex gap-2.5 text-sm leading-snug">
                    <span className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${severity === "critical" ? "bg-danger" : severity === "high" ? "bg-warn" : "bg-ink-faint"}`} />
                    <span className="text-ink-muted">
                      <span className={`font-semibold uppercase text-[10px] tracking-wider mr-1.5 ${SEVERITY[severity]}`}>
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

const Why: React.FC = () => (
  <section id="why" className="scroll-mt-20 border-t border-line bg-surface">
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
      <div className="max-w-2xl">
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-ink">
          Most fraud systems score the wrong side, too late
        </h2>
        <p className="mt-4 text-ink-muted leading-relaxed">
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
          <div key={title} className="rounded-xl border border-line bg-canvas p-5">
            <Icon className="h-5 w-5 text-brand" />
            <h3 className="mt-3 font-semibold text-ink">{title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{body}</p>
          </div>
        ))}
      </div>
    </div>
  </section>
);

const How: React.FC = () => (
  <section id="how" className="scroll-mt-20 border-t border-line">
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
      <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-ink">How it works</h2>
      <p className="mt-3 text-ink-muted max-w-2xl">
        Four checks run against every payee, and the strongest signal decides.
        Weaker signals add to it, so a pile of small doubts can still reach a
        step-up, but one critical finding never gets averaged away.
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
        ].map(({ n, icon: Icon, title, body }) => (
          <li key={n} className="relative rounded-xl border border-line bg-surface p-5 shadow-card">
            <div className="flex items-center justify-between">
              <Icon className="h-5 w-5 text-brand" />
              <span className="font-mono text-xs font-semibold text-ink-faint">{n}</span>
            </div>
            <h3 className="mt-3 font-semibold text-ink">{title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{body}</p>
          </li>
        ))}
      </ol>

      <div className="mt-8 rounded-xl border border-line bg-raised p-5 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
        <span className="font-semibold text-ink">The verdict:</span>
        {[
          ["APPROVE", "text-ok"],
          ["WARN", "text-ink-muted"],
          ["STEP UP", "text-warn"],
          ["BLOCK", "text-danger"],
        ].map(([label, tone], i) => (
          <React.Fragment key={label}>
            {i > 0 && <span className="text-ink-faint">→</span>}
            <span className={`font-mono font-semibold ${tone}`}>{label}</span>
          </React.Fragment>
        ))}
        <span className="text-ink-muted w-full sm:w-auto sm:ml-2">
          Every verdict comes with the findings that produced it, in words.
        </span>
      </div>
    </div>
  </section>
);

const Catches: React.FC = () => {
  const [active, setActive] = useState(EXAMPLES[0].key);
  const example = EXAMPLES.find((e) => e.key === active) ?? EXAMPLES[0];
  const tone = TONE[example.tone];

  return (
    <section id="catches" className="scroll-mt-20 border-t border-line bg-surface">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-ink">
          What it catches
        </h2>
        <p className="mt-3 text-ink-muted max-w-2xl">
          Three patterns, written out as the check would report them. These are
          worked examples, not live results.
        </p>

        <div className="mt-8 grid lg:grid-cols-[16rem_1fr] gap-6">
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
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-left shrink-0 transition ${
                    isActive
                      ? "border-brand/30 bg-brand/10 text-ink"
                      : "border-line bg-canvas text-ink-muted hover:text-ink hover:border-line-strong"
                  }`}
                >
                  <Icon className={`h-4 w-4 shrink-0 ${isActive ? "text-brand" : "text-ink-subtle"}`} />
                  <span className="text-sm font-medium whitespace-nowrap">{item.tab}</span>
                </button>
              );
            })}
          </div>

          <div className="rounded-2xl border border-line bg-canvas p-5 sm:p-6">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-subtle">
              Payee
            </div>
            <div className="mt-2 font-mono text-sm text-ink break-all">{example.input}</div>

            <div className="mt-5 flex items-center gap-3">
              <span className={`px-2.5 py-1 rounded-md border text-xs font-bold tracking-wide ${tone.chip}`}>
                {example.verdict}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-raised overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${tone.bar}`}
                  style={{ width: `${example.score}%` }}
                />
              </div>
              <span className="text-sm font-bold text-ink tabular-nums">{example.score}</span>
            </div>

            <ul className="mt-5 space-y-3">
              {example.findings.map(([severity, text]) => (
                <li key={text} className="flex gap-3 text-sm leading-relaxed">
                  <span
                    className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${
                      severity === "critical"
                        ? "bg-danger"
                        : severity === "high"
                        ? "bg-warn"
                        : "bg-ink-faint"
                    }`}
                  />
                  <span className="text-ink-muted">
                    <span
                      className={`font-semibold uppercase text-[10px] tracking-wider mr-2 ${SEVERITY[severity]}`}
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

const Evidence: React.FC = () => (
  <section id="evidence" className="scroll-mt-20 border-t border-line">
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
      <div className="grid lg:grid-cols-[1fr_1.1fr] gap-10 items-start">
        <div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-ink">
            Measured, and honest about it
          </h2>
          <p className="mt-4 text-ink-muted leading-relaxed">
            Fraud is rare, so accuracy is a meaningless score — a model that
            approves everything looks excellent. These are the numbers that
            actually say something: how well the model ranks fraud above
            legitimate payments, and how much it catches while wrongly
            flagging one legitimate payment in a hundred.
          </p>
          <p className="mt-4 text-sm text-ink-subtle leading-relaxed">
            The classifier is trained on a simulator, so these figures
            demonstrate the method rather than field performance. The
            simulator was deliberately rebuilt to be hard: an earlier, easier
            version scored 0.99 and that was a red flag, not a result.
          </p>
        </div>

        <div className="rounded-2xl border border-line bg-surface shadow-card overflow-hidden">
          <div className="grid grid-cols-[1fr_auto_auto] text-xs">
            <div className="px-5 py-3 font-semibold text-ink-subtle uppercase tracking-wider text-[10px] border-b border-line">
              Metric
            </div>
            <div className="px-4 py-3 font-semibold text-ink uppercase tracking-wider text-[10px] border-b border-line text-right">
              This model
            </div>
            <div className="px-5 py-3 font-semibold text-ink-subtle uppercase tracking-wider text-[10px] border-b border-line text-right">
              Baseline
            </div>

            {[
              ["PR-AUC", "0.62", "0.18", "Ranking quality where fraud is rare"],
              ["ROC-AUC", "0.98", "0.95", "Overall separation"],
              ["Recall at 1% false positives", "68.4%", "23.9%", "Caught, within a realistic alert budget"],
            ].map(([label, mine, base, note]) => (
              <React.Fragment key={label}>
                <div className="px-5 py-4 border-b border-line last:border-0">
                  <div className="text-sm font-medium text-ink">{label}</div>
                  <div className="text-[11px] text-ink-subtle mt-0.5">{note}</div>
                </div>
                <div className="px-4 py-4 border-b border-line last:border-0 text-right">
                  <span className="text-lg font-bold text-brand tabular-nums">{mine}</span>
                </div>
                <div className="px-5 py-4 border-b border-line last:border-0 text-right">
                  <span className="text-sm text-ink-subtle tabular-nums">{base}</span>
                </div>
              </React.Fragment>
            ))}
          </div>
          <div className="px-5 py-3 bg-raised border-t border-line text-[11px] text-ink-subtle">
            Baseline is logistic regression on the same features. An ablation
            shows the payee-side checks carry 22.6% of social-engineering
            recall on their own, and 58.4% together with the payer side.
          </div>
        </div>
      </div>
    </div>
  </section>
);

const Cta: React.FC<LandingProps> = ({ onCreateAccount }) => (
  <section className="border-t border-line bg-surface">
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20 text-center">
      <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-ink">
        Start with one payee
      </h2>
      <p className="mt-3 text-ink-muted max-w-xl mx-auto">
        Sign up with your UPI ID, paste an address or a scanned QR, and read
        the findings. Upload a statement afterwards and the check starts using
        your own history too.
      </p>
      <button
        onClick={onCreateAccount}
        className="mt-7 inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold text-white bg-brand-ink hover:opacity-90 transition shadow-lift"
      >
        Create an account
        <ArrowRight className="h-4 w-4" />
      </button>
      <p className="mt-5 text-xs text-ink-subtle flex items-center justify-center gap-1.5">
        <BadgeCheck className="h-3.5 w-3.5 shrink-0" />
        Nothing here moves money. The system reads and scores; it never pays.
      </p>
    </div>
  </section>
);

const Footer: React.FC = () => (
  <footer className="border-t border-line">
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4">
      <div className="flex items-center gap-2 text-sm text-ink-subtle">
        <LogoMark className="h-4 w-4" />
        Edge AI UPI Behavioural Risk Intelligence System
      </div>
      <div className="flex items-center gap-4 text-xs text-ink-subtle">
        <span className="inline-flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5" />
          Final-year project · not a licensed payment service
        </span>
      </div>
    </div>
  </footer>
);

export const Landing: React.FC<LandingProps> = (props) => (
  <div className="min-h-screen bg-canvas text-ink font-sans">
    <LandingHeader {...props} />
    <main>
      <Hero {...props} />
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
