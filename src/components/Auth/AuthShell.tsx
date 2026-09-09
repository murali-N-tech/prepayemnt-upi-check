import React from "react";
import { ArrowLeft, GitBranch, QrCode, ScanLine } from "lucide-react";
import { LogoMark, Wordmark } from "../ui/Logo";
import { ThemeToggle } from "../ui/ThemeToggle";

interface AuthShellProps {
  title: string;
  subtitle: string;
  onBack?: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
}

const POINTS = [
  { icon: ScanLine, text: "Look-alike UPI IDs and confusable bank handles" },
  { icon: QrCode, text: "QR codes whose displayed name is not the account they pay" },
  { icon: GitBranch, text: "Accounts collecting one payment each from many strangers" },
];

/** Both auth screens share this frame so they cannot drift apart, and so the
 *  sign-in page still explains what the product is to someone who arrived
 *  from a link rather than the landing page. */
export const AuthShell: React.FC<AuthShellProps> = ({
  title,
  subtitle,
  onBack,
  children,
  footer,
}) => (
  <div className="min-h-screen bg-canvas text-ink font-sans lg:grid lg:grid-cols-[1fr_1.05fr]">
    {/* Left: the form. */}
    <div className="flex flex-col min-h-screen lg:min-h-0">
      <div className="flex items-center gap-3 p-4 sm:p-6">
        {onBack ? (
          <button
            onClick={onBack}
            className="inline-flex items-center gap-2 px-2.5 py-1.5 -ml-1 rounded-lg text-sm text-ink-muted hover:text-ink hover:bg-raised transition"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
        ) : (
          <Wordmark subtitle="Behavioural risk" />
        )}
        <div className="flex-1" />
        <ThemeToggle compact />
      </div>

      <div className="flex-1 flex items-center justify-center px-4 sm:px-6 pb-10">
        <div className="w-full max-w-sm animate-rise">
          <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
          <p className="mt-1.5 text-sm text-ink-muted">{subtitle}</p>

          <div className="mt-8">{children}</div>

          <div className="mt-8 text-sm text-ink-muted text-center">{footer}</div>
        </div>
      </div>
    </div>

    {/* Right: what they are signing in to. Hidden on phones, where the form
        is the only thing worth the screen. */}
    <div className="hidden lg:flex flex-col justify-center relative border-l border-line bg-surface overflow-hidden">
      <div className="absolute inset-0 hero-grid pointer-events-none" aria-hidden="true" />
      <div className="relative px-12 xl:px-16 py-16 max-w-lg">
        <span className="grid place-items-center h-11 w-11 rounded-xl bg-brand/12 text-brand border border-brand/25">
          <LogoMark className="h-6 w-6" />
        </span>
        <h2 className="mt-6 text-2xl font-bold tracking-tight text-ink leading-snug">
          Check who you are paying before the money leaves.
        </h2>
        <p className="mt-4 text-ink-muted leading-relaxed">
          UPI settles in seconds and does not reverse. The checks run on the
          payee, in the moment before you approve.
        </p>
        <ul className="mt-8 space-y-4">
          {POINTS.map(({ icon: Icon, text }) => (
            <li key={text} className="flex gap-3">
              <span className="grid place-items-center h-8 w-8 rounded-lg bg-canvas border border-line text-brand shrink-0">
                <Icon className="h-4 w-4" />
              </span>
              <span className="text-sm leading-relaxed text-ink-muted pt-1.5">{text}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  </div>
);

/** One input style, defined once. */
export const fieldClass = (invalid = false) =>
  `w-full px-3.5 py-2.5 rounded-lg bg-inset border text-ink placeholder-ink-subtle transition ${
    invalid ? "border-warn" : "border-line hover:border-line-strong"
  }`;

export const labelClass = "block text-sm font-medium text-ink-muted mb-1.5";

export const submitClass =
  "w-full py-2.5 px-4 rounded-lg bg-brand-ink text-white font-semibold shadow-card hover:opacity-90 transition disabled:opacity-50 disabled:cursor-not-allowed";
