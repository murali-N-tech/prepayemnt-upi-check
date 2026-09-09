import React from "react";

/** The mark: a shield whose lower half is a payment arrow being stopped.
 *
 * Drawn inline rather than loaded as an image so it inherits currentColor and
 * stays crisp in both themes.
 */
export const LogoMark: React.FC<{ className?: string }> = ({ className = "h-6 w-6" }) => (
  <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
    <path
      d="M12 2.5 4.5 5.4v6.1c0 4.6 3.1 8.7 7.5 10 4.4-1.3 7.5-5.4 7.5-10V5.4L12 2.5Z"
      className="fill-current opacity-15"
    />
    <path
      d="M12 2.5 4.5 5.4v6.1c0 4.6 3.1 8.7 7.5 10 4.4-1.3 7.5-5.4 7.5-10V5.4L12 2.5Z"
      className="stroke-current"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
    <path
      d="M8.4 12.2h5.9m0 0-2.1-2.2m2.1 2.2-2.1 2.2"
      className="stroke-current"
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
    <span className="grid place-items-center h-9 w-9 rounded-xl bg-brand/12 text-brand border border-brand/25 shrink-0">
      <LogoMark className="h-5 w-5" />
    </span>
    <div className="min-w-0">
      <div className="font-bold tracking-tight text-ink leading-tight truncate">
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
