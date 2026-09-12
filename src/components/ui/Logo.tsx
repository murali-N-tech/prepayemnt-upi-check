import React from "react";

/** The mark: a shield whose lower half is a payment arrow being stopped.
 *
 * Drawn inline rather than loaded as an image so it inherits currentColor and
 * stays crisp in both themes.
 */
// `style` is accepted as well as `className`: Landing.tsx's footer colours the
// mark with `style={{ color: "var(--brand)" }}`, and without it in the prop type
// `tsc --noEmit` fails - which is the first half of `npm run build`, so the
// Vercel build fails with it. The `as any` at the call site casts the style
// OBJECT, not the prop, so it never suppressed the error.
export const LogoMark: React.FC<{ className?: string; style?: React.CSSProperties }> = ({
  className = "h-6 w-6",
  style,
}) => (
  <svg viewBox="0 0 24 24" fill="none" className={className} style={style} aria-hidden="true">
    <defs>
      <linearGradient id="logoGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="var(--brand)" />
        <stop offset="100%" stopColor="var(--violet, #7c3aed)" />
      </linearGradient>
    </defs>
    <path
      d="M12 2.5 4.5 5.4v6.1c0 4.6 3.1 8.7 7.5 10 4.4-1.3 7.5-5.4 7.5-10V5.4L12 2.5Z"
      fill="url(#logoGrad)"
      opacity="0.18"
    />
    <path
      d="M12 2.5 4.5 5.4v6.1c0 4.6 3.1 8.7 7.5 10 4.4-1.3 7.5-5.4 7.5-10V5.4L12 2.5Z"
      stroke="url(#logoGrad)"
      strokeWidth="1.6"
      strokeLinejoin="round"
      fill="none"
    />
    <path
      d="M8.4 12.2h5.9m0 0-2.1-2.2m2.1 2.2-2.1 2.2"
      stroke="url(#logoGrad)"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const Wordmark: React.FC<{ subtitle?: string; compact?: boolean }> = ({
  subtitle,
  compact = false,
}) => (
  <div className="flex items-center gap-2.5 min-w-0">
    <span
      className="grid place-items-center h-9 w-9 rounded-xl shrink-0 transition-transform hover:scale-105"
      style={{
        background: "linear-gradient(135deg, color-mix(in oklab, var(--brand) 15%, transparent), color-mix(in oklab, var(--violet, #7c3aed) 12%, transparent))",
        border: "1px solid color-mix(in oklab, var(--brand) 30%, transparent)",
        boxShadow: "0 0 12px color-mix(in oklab, var(--brand) 20%, transparent)",
      }}
    >
      <LogoMark className="h-5 w-5" />
    </span>
    <div className="min-w-0">
      <div
        className="font-bold tracking-tight leading-tight truncate"
        style={{
          background: "linear-gradient(135deg, var(--brand) 0%, var(--violet, #7c3aed) 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        {compact ? "Edge UPI" : "Edge AI UPI"}
      </div>
      {subtitle && (
        <div className="hidden sm:block text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-subtle font-mono truncate">
          {subtitle}
        </div>
      )}
    </div>
  </div>
);

export default Wordmark;
