import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, GitBranch, QrCode, ScanLine, Shield, Zap, Lock } from "lucide-react";
import { LogoMark, Wordmark } from "../ui/Logo";
import { ThemeToggle } from "../ui/ThemeToggle";

/* ─────────────────────────────────────────────────────────────────────────
   Types
   ───────────────────────────────────────────────────────────────────────── */

interface AuthShellProps {
  title: string;
  subtitle: string;
  onBack?: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
}

/* ─────────────────────────────────────────────────────────────────────────
   Constants
   ───────────────────────────────────────────────────────────────────────── */

const POINTS = [
  { icon: ScanLine,  text: "Look-alike UPI IDs and confusable bank handles" },
  { icon: QrCode,    text: "QR codes whose displayed name is not the account they pay" },
  { icon: GitBranch, text: "Accounts collecting one payment each from many strangers" },
];

/* ─────────────────────────────────────────────────────────────────────────
   3D Floating Shapes (CSS only — no canvas)
   ───────────────────────────────────────────────────────────────────────── */

const SHAPES = [
  /* large cube back-left */
  {
    key: "c1",
    size: 80,
    top: "8%",  left: "4%",
    rot: "rotateX(30deg) rotateY(-40deg)",
    delay: "0s", dur: "14s",
    color: "var(--brand)",
    opacity: 0.18,
  },
  /* medium sphere top-right */
  {
    key: "s1",
    size: 56,
    top: "12%", left: "80%",
    rot: "rotateX(10deg) rotateY(25deg)",
    delay: "2s", dur: "18s",
    color: "var(--violet, #7c3aed)",
    opacity: 0.22,
    round: true,
  },
  /* small cube mid-left */
  {
    key: "c2",
    size: 42,
    top: "50%", left: "6%",
    rot: "rotateX(45deg) rotateY(20deg)",
    delay: "4s", dur: "11s",
    color: "var(--cyan, #0891b2)",
    opacity: 0.2,
  },
  /* ring bottom-right */
  {
    key: "r1",
    size: 100,
    top: "72%", left: "78%",
    rot: "rotateX(60deg) rotateY(-15deg)",
    delay: "1.5s", dur: "20s",
    color: "var(--pink, #db2777)",
    opacity: 0.14,
    ring: true,
  },
  /* tiny cube center */
  {
    key: "c3",
    size: 28,
    top: "40%", left: "50%",
    rot: "rotateX(20deg) rotateY(55deg)",
    delay: "6s", dur: "16s",
    color: "var(--brand)",
    opacity: 0.25,
  },
  /* medium ring top-center */
  {
    key: "r2",
    size: 66,
    top: "2%", left: "45%",
    rot: "rotateX(70deg) rotateY(10deg)",
    delay: "3s", dur: "22s",
    color: "var(--violet, #7c3aed)",
    opacity: 0.16,
    ring: true,
  },
  /* large sphere bottom-left */
  {
    key: "s2",
    size: 90,
    top: "75%", left: "12%",
    rot: "rotateX(15deg) rotateY(-30deg)",
    delay: "8s", dur: "17s",
    color: "var(--brand)",
    opacity: 0.12,
    round: true,
  },
];

const FloatingShapes: React.FC = () => (
  <div
    className="absolute inset-0 pointer-events-none overflow-hidden"
    style={{ perspective: "900px", perspectiveOrigin: "50% 50%" }}
  >
    {SHAPES.map((s) => (
      <div
        key={s.key}
        style={{
          position: "absolute",
          top: s.top,
          left: s.left,
          width: s.size,
          height: s.size,
          transform: s.rot,
          borderRadius: s.round ? "50%" : s.ring ? "50%" : "12px",
          background: s.ring
            ? "transparent"
            : `radial-gradient(circle at 35% 30%, color-mix(in oklab, ${s.color} 60%, white), color-mix(in oklab, ${s.color} 80%, transparent))`,
          border: s.ring ? `3px solid color-mix(in oklab, ${s.color} 50%, transparent)` : "none",
          opacity: s.opacity,
          boxShadow: s.ring
            ? `0 0 20px color-mix(in oklab, ${s.color} 30%, transparent), inset 0 0 20px color-mix(in oklab, ${s.color} 10%, transparent)`
            : `4px 8px 24px color-mix(in oklab, ${s.color} 35%, transparent), inset -2px -4px 12px color-mix(in oklab, ${s.color} 25%, transparent)`,
          animation: `float ${s.dur} ease-in-out infinite`,
          animationDelay: s.delay,
        }}
      />
    ))}
  </div>
);

/* ─────────────────────────────────────────────────────────────────────────
   3D Perspective Grid Background
   ───────────────────────────────────────────────────────────────────────── */

const PerspectiveGrid: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      overflow: "hidden",
      pointerEvents: "none",
    }}
  >
    {/* Perspective grid floor */}
    <div
      style={{
        position: "absolute",
        bottom: 0,
        left: "-50%",
        right: "-50%",
        height: "55%",
        backgroundImage: `
          linear-gradient(to right, color-mix(in oklab, var(--brand) 12%, transparent) 1px, transparent 1px),
          linear-gradient(to bottom, color-mix(in oklab, var(--brand) 10%, transparent) 1px, transparent 1px)
        `,
        backgroundSize: "60px 60px",
        transform: "perspective(500px) rotateX(75deg)",
        transformOrigin: "50% 100%",
        maskImage: "linear-gradient(to top, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.1) 60%, transparent 100%)",
        WebkitMaskImage: "linear-gradient(to top, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.1) 60%, transparent 100%)",
      }}
    />
    {/* Radial vignette overlay */}
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "radial-gradient(ellipse 80% 70% at 50% 50%, transparent 40%, color-mix(in oklab, var(--canvas) 70%, transparent) 100%)",
      }}
    />
  </div>
);

/* ─────────────────────────────────────────────────────────────────────────
   Tilt Card — 3D mouse-tracking form card
   ───────────────────────────────────────────────────────────────────────── */

const TiltCard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const cardRef = useRef<HTMLDivElement>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const [isHovered, setIsHovered] = useState(false);
  const frameRef = useRef<number>(0);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    cancelAnimationFrame(frameRef.current);
    frameRef.current = requestAnimationFrame(() => {
      const rect = cardRef.current!.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) / (rect.width / 2);   // -1 to +1
      const dy = (e.clientY - cy) / (rect.height / 2);  // -1 to +1
      setTilt({ x: dy * -10, y: dx * 10 }); // max ±10deg
    });
  }, []);

  const handleMouseLeave = useCallback(() => {
    cancelAnimationFrame(frameRef.current);
    setIsHovered(false);
    setTilt({ x: 0, y: 0 });
  }, []);

  useEffect(() => () => cancelAnimationFrame(frameRef.current), []);

  return (
    <div
      style={{ perspective: "1200px", perspectiveOrigin: "50% 40%" }}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
    >
      <div
        ref={cardRef}
        style={{
          transform: `rotateX(${tilt.x}deg) rotateY(${tilt.y}deg) translateZ(0)`,
          transformStyle: "preserve-3d",
          transition: isHovered
            ? "transform 0.1s ease-out"
            : "transform 0.6s cubic-bezier(0.22,1,0.36,1)",
          willChange: "transform",
        }}
      >
        {/* Card shine layer — follows tilt direction */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: "1.25rem",
            background: `linear-gradient(${135 + tilt.y * 2}deg, rgba(255,255,255,${0.04 + Math.abs(tilt.x + tilt.y) * 0.003}) 0%, transparent 60%)`,
            pointerEvents: "none",
            zIndex: 2,
            transition: "background 0.1s ease-out",
          }}
        />
        {/* Card shadow that deepens with tilt */}
        <div
          style={{
            position: "absolute",
            inset: -2,
            borderRadius: "1.375rem",
            background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
            opacity: 0.25 + Math.abs(tilt.x + tilt.y) * 0.01,
            filter: "blur(18px)",
            transform: `translateY(${8 + Math.abs(tilt.x) * 1.5}px) translateX(${tilt.y * 0.8}px)`,
            transition: isHovered ? "all 0.12s ease-out" : "all 0.6s cubic-bezier(0.22,1,0.36,1)",
            zIndex: -1,
          }}
        />
        {children}
      </div>
    </div>
  );
};

/* ─────────────────────────────────────────────────────────────────────────
   Glowing Stat Card (right panel)
   ───────────────────────────────────────────────────────────────────────── */

const StatCard: React.FC<{
  icon: React.FC<{ className?: string; style?: React.CSSProperties }>;
  label: string;
  value: string;
  delay: string;
}> = ({ icon: Icon, label, value, delay }) => (
  <div
    className="animate-rise"
    style={{
      animationDelay: delay,
      padding: "14px 16px",
      borderRadius: "1rem",
      background: "color-mix(in oklab, var(--surface) 60%, transparent)",
      border: "1px solid color-mix(in oklab, var(--brand) 20%, transparent)",
      backdropFilter: "blur(12px)",
      boxShadow: "0 4px 20px color-mix(in oklab, var(--brand) 10%, transparent), inset 0 1px 0 rgba(255,255,255,0.05)",
      display: "flex",
      alignItems: "center",
      gap: "12px",
      transform: "translateZ(20px)",
    }}
  >
    <span
      style={{
        display: "grid",
        placeItems: "center",
        width: 36,
        height: 36,
        borderRadius: "10px",
        background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
        boxShadow: "0 4px 12px var(--glow-brand, rgba(99,102,241,0.4))",
        flexShrink: 0,
      }}
    >
      <Icon className="h-4 w-4" style={{ color: "#fff" }} />
    </span>
    <div>
      <div style={{ fontSize: 18, fontWeight: 800, color: "var(--ink)", lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--ink-subtle)", marginTop: 2 }}>{label}</div>
    </div>
  </div>
);

/* ─────────────────────────────────────────────────────────────────────────
   Main AuthShell Export
   ───────────────────────────────────────────────────────────────────────── */

export const AuthShell: React.FC<AuthShellProps> = ({
  title,
  subtitle,
  onBack,
  children,
  footer,
}) => {
  return (
    <div
      className="min-h-screen font-sans relative"
      style={{ background: "var(--canvas)", color: "var(--ink)", overflow: "hidden" }}
    >
      {/* ── Global 3D background ──────────────────────────────────────── */}
      {/* Ambient blobs */}
      <div
        className="blob"
        style={{
          width: 700, height: 700,
          top: -250, left: -150,
          background: "color-mix(in oklab, var(--brand) 12%, transparent)",
          animationDuration: "16s",
        }}
      />
      <div
        className="blob"
        style={{
          width: 500, height: 500,
          top: 100, right: -180,
          background: "color-mix(in oklab, var(--violet, #7c3aed) 10%, transparent)",
          animationDelay: "5s",
          animationDuration: "20s",
        }}
      />
      <div
        className="blob"
        style={{
          width: 400, height: 400,
          bottom: -100, left: "40%",
          background: "color-mix(in oklab, var(--pink, #db2777) 8%, transparent)",
          animationDelay: "10s",
          animationDuration: "24s",
        }}
      />

      {/* 3D floating geometric shapes */}
      <FloatingShapes />

      {/* Perspective floor grid */}
      <PerspectiveGrid />

      {/* ── Layout ───────────────────────────────────────────────────── */}
      <div
        className="relative min-h-screen lg:grid"
        style={{ gridTemplateColumns: "1fr 1.05fr", zIndex: 1 }}
      >
        {/* ── LEFT: Form column ─────────────────────────────────────── */}
        <div className="flex flex-col min-h-screen lg:min-h-0">
          {/* Top bar */}
          <div className="flex items-center gap-3 p-4 sm:p-6 relative z-10">
            {onBack ? (
              <button
                onClick={onBack}
                className="group inline-flex items-center gap-2 px-3 py-1.5 -ml-1 rounded-xl text-sm font-semibold transition-all hover:scale-[1.03]"
                style={{
                  color: "var(--ink-muted)",
                  background: "color-mix(in oklab, var(--surface) 70%, transparent)",
                  border: "1px solid color-mix(in oklab, var(--line) 80%, transparent)",
                  backdropFilter: "blur(12px)",
                }}
              >
                <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-1" />
                Back
              </button>
            ) : (
              <Wordmark subtitle="Behavioural risk" />
            )}
            <div className="flex-1" />
            <ThemeToggle compact />
          </div>

          {/* 3D tilting form card */}
          <div className="flex-1 flex items-center justify-center px-4 sm:px-6 pb-10">
            <div className="w-full max-w-sm">
              <TiltCard>
                {/* Card body */}
                <div
                  className="relative rounded-2xl p-8"
                  style={{
                    background: "color-mix(in oklab, var(--surface) 90%, transparent)",
                    border: "1px solid color-mix(in oklab, var(--brand) 20%, transparent)",
                    backdropFilter: "blur(24px)",
                    WebkitBackdropFilter: "blur(24px)",
                    boxShadow: "0 0 0 1px color-mix(in oklab, var(--line) 60%, transparent)",
                  }}
                >
                  {/* Gradient top edge accent */}
                  <div
                    style={{
                      position: "absolute",
                      top: 0,
                      left: "15%",
                      right: "15%",
                      height: 2,
                      borderRadius: "0 0 4px 4px",
                      background: "linear-gradient(to right, transparent, var(--brand), var(--violet, #7c3aed), transparent)",
                    }}
                  />

                  {/* Logo badge */}
                  <div className="flex items-center gap-3 mb-6">
                    <span
                      className="grid place-items-center h-11 w-11 rounded-xl"
                      style={{
                        background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
                        boxShadow: "0 6px 20px var(--glow-brand, rgba(99,102,241,0.45)), inset 0 1px 0 rgba(255,255,255,0.15)",
                        transform: "translateZ(30px)",
                      }}
                    >
                      <LogoMark className="h-6 w-6 text-white" />
                    </span>
                    <div>
                      <div
                        className="text-xs font-bold uppercase tracking-widest"
                        style={{ color: "var(--brand)" }}
                      >
                        Edge AI UPI
                      </div>
                      <div className="text-[10px]" style={{ color: "var(--ink-subtle)" }}>
                        Behavioural Risk Intelligence
                      </div>
                    </div>
                  </div>

                  {/* Title */}
                  <h1
                    className="text-2xl font-extrabold tracking-tight"
                    style={{ color: "var(--ink)", transform: "translateZ(20px)", display: "block" }}
                  >
                    {title}
                  </h1>
                  <p
                    className="mt-1.5 text-sm"
                    style={{ color: "var(--ink-muted)" }}
                  >
                    {subtitle}
                  </p>

                  {/* Slot for form */}
                  <div className="mt-7">{children}</div>

                  {/* Footer */}
                  <div className="mt-7 text-sm text-center" style={{ color: "var(--ink-muted)" }}>
                    {footer}
                  </div>
                </div>
              </TiltCard>

              {/* Hint below card */}
              <p
                className="mt-5 text-center text-xs flex items-center justify-center gap-1.5"
                style={{ color: "var(--ink-subtle)" }}
              >
                <Lock className="h-3 w-3" />
                Secured with JWT · Nothing here moves money
              </p>
            </div>
          </div>
        </div>

        {/* ── RIGHT: 3D depth panel (hidden on mobile) ──────────────── */}
        <div
          className="hidden lg:flex flex-col justify-center relative overflow-hidden border-l"
          style={{
            borderColor: "color-mix(in oklab, var(--line) 50%, transparent)",
            background: "color-mix(in oklab, var(--surface) 30%, transparent)",
            backdropFilter: "blur(40px)",
          }}
        >
          {/* Inner perspective container */}
          <div
            className="relative px-12 xl:px-16 py-16 max-w-lg"
            style={{ perspective: "1000px" }}
          >
            {/* Glowing large logo — front layer */}
            <div
              className="animate-rise mb-8"
              style={{ transform: "perspective(600px) translateZ(30px)" }}
            >
              <span
                className="grid place-items-center h-16 w-16 rounded-2xl"
                style={{
                  background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
                  boxShadow:
                    "0 0 0 1px color-mix(in oklab, var(--brand) 35%, transparent), 0 0 40px var(--glow-brand, rgba(99,102,241,0.5)), 0 12px 32px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.15)",
                }}
              >
                <LogoMark className="h-8 w-8 text-white" />
              </span>
            </div>

            {/* Headline */}
            <h2
              className="text-[1.65rem] font-extrabold tracking-tight leading-snug animate-rise"
              style={{ color: "var(--ink)", animationDelay: "60ms" }}
            >
              Check who you are paying{" "}
              <span
                style={{
                  background:
                    "linear-gradient(135deg, var(--brand) 0%, var(--violet, #7c3aed) 50%, var(--pink, #db2777) 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                before the money leaves.
              </span>
            </h2>
            <p
              className="mt-4 leading-relaxed text-sm animate-rise"
              style={{ color: "var(--ink-muted)", animationDelay: "120ms" }}
            >
              UPI settles in seconds and does not reverse. Checks run on the
              payee — in the moment before you approve.
            </p>

            {/* 3D floating stat cards */}
            <div className="mt-8 space-y-3">
              <StatCard icon={Shield}   value="0.98"  label="ROC-AUC — overall separation"      delay="180ms" />
              <StatCard icon={Zap}      value="68.4%" label="Recall at 1% false-positive rate"   delay="260ms" />
              <StatCard icon={ScanLine} value="< 500ms" label="Check latency before you tap Pay" delay="340ms" />
            </div>

            {/* Feature bullets */}
            <ul className="mt-8 space-y-3.5">
              {POINTS.map(({ icon: Icon, text }, idx) => (
                <li
                  key={text}
                  className="flex gap-3 animate-rise"
                  style={{ animationDelay: `${400 + idx * 80}ms` }}
                >
                  <span
                    className="grid place-items-center h-8 w-8 rounded-xl shrink-0"
                    style={{
                      background:
                        "linear-gradient(135deg, color-mix(in oklab, var(--brand) 18%, var(--raised)), color-mix(in oklab, var(--violet, #7c3aed) 12%, var(--raised)))",
                      border: "1px solid color-mix(in oklab, var(--brand) 25%, transparent)",
                      boxShadow: "0 2px 10px color-mix(in oklab, var(--brand) 18%, transparent)",
                    }}
                  >
                    <Icon className="h-3.5 w-3.5" style={{ color: "var(--brand)" }} />
                  </span>
                  <span
                    className="text-sm leading-relaxed pt-1"
                    style={{ color: "var(--ink-muted)" }}
                  >
                    {text}
                  </span>
                </li>
              ))}
            </ul>

            {/* Decorative floating card behind content */}
            <div
              style={{
                position: "absolute",
                bottom: 40,
                right: -20,
                width: 140,
                height: 80,
                borderRadius: 16,
                background:
                  "linear-gradient(135deg, color-mix(in oklab, var(--brand) 15%, var(--surface)), color-mix(in oklab, var(--violet, #7c3aed) 10%, var(--surface)))",
                border: "1px solid color-mix(in oklab, var(--brand) 20%, transparent)",
                boxShadow: "0 8px 32px color-mix(in oklab, var(--brand) 15%, transparent)",
                transform: "perspective(400px) rotateY(-12deg) rotateX(5deg) translateZ(-40px)",
                opacity: 0.45,
              }}
            />
            <div
              style={{
                position: "absolute",
                top: 60,
                right: -30,
                width: 100,
                height: 60,
                borderRadius: 12,
                background: "color-mix(in oklab, var(--violet, #7c3aed) 12%, var(--surface))",
                border: "1px solid color-mix(in oklab, var(--violet, #7c3aed) 20%, transparent)",
                transform: "perspective(400px) rotateY(-18deg) rotateX(-8deg) translateZ(-80px)",
                opacity: 0.3,
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

/* ─────────────────────────────────────────────────────────────────────────
   Utility exports (unchanged contract for Login / Register)
   ───────────────────────────────────────────────────────────────────────── */

/** One input style, defined once. */
export const fieldClass = (invalid = false) =>
  `w-full px-3.5 py-2.5 rounded-xl bg-inset transition-all duration-150 font-sans ${
    invalid
      ? "border border-warn text-ink"
      : "border border-line text-ink hover:border-brand/40"
  }`;

export const labelClass = "block text-sm font-semibold mb-1.5 text-ink-muted";

export const submitClass =
  "w-full py-3 px-4 rounded-xl font-bold text-white shadow-card transition-all duration-150 hover:scale-[1.02] hover:opacity-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:scale-100";

/** Gradient style for submit — applied via style prop */
export const submitStyle: React.CSSProperties = {
  background: "linear-gradient(135deg, var(--brand-ink), var(--violet, #7c3aed))",
  boxShadow: "0 4px 18px var(--glow-brand, rgba(99,102,241,0.4)), inset 0 1px 0 rgba(255,255,255,0.12)",
};
