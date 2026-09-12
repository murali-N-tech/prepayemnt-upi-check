import React, { useEffect, useRef, useState } from "react";
import { BadgeCheck, ChevronDown, LogOut, Menu, Server, ShieldQuestion } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { useHealth } from "../../lib/useHealth";
import { navItem, type PageID } from "./nav";
import { Wordmark } from "../ui/Logo";
import { ThemeToggle } from "../ui/ThemeToggle";
import BackendSettingsModal from "../BackendSettingsModal";
import { getStoredBackendUrl, isCapacitorNative } from "../../services/apiConfig";

interface AppHeaderProps {
  activePage: PageID;
  onOpenMenu: () => void;
}

const StatusPill: React.FC = () => {
  const health = useHealth();

  const tone =
    health === null
      ? { dot: "bg-ink-faint", text: "Checking", detail: "Contacting the server", glow: "transparent" }
      : health.status === "ok"
      ? { dot: "bg-ok", text: "All systems up", detail: "Express, Python and the model are ready", glow: "var(--glow-ok, rgba(4,120,87,0.35))" }
      : {
          dot: "bg-warn",
          text: "Degraded",
          detail:
            health.model_detail ??
            `backend: ${health.backend}, model: ${health.model}`,
          glow: "var(--glow-warn, rgba(180,83,9,0.35))",
        };

  return (
    <span
      title={tone.detail}
      className="hidden md:inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-all"
      style={{
        background: "color-mix(in oklab, var(--raised) 80%, transparent)",
        border: "1px solid var(--line)",
        color: "var(--ink-muted)",
        backdropFilter: "blur(8px)",
      }}
    >
      {/* Pulsing dot */}
      <span className="relative flex h-2 w-2">
        <span
          className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-50"
          style={{ background: health?.status === "ok" ? "var(--ok)" : health === null ? "var(--ink-faint)" : "var(--warn)" }}
        />
        <span
          className="relative inline-flex rounded-full h-2 w-2"
          style={{ background: health?.status === "ok" ? "var(--ok)" : health === null ? "var(--ink-faint)" : "var(--warn)" }}
        />
      </span>
      {tone.text}
    </span>
  );
};

export const AppHeader: React.FC<AppHeaderProps> = ({ activePage, onOpenMenu }) => {
  const { username, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const current = navItem(activePage);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const isUpiId = (username ?? "").includes("@");

  // Get first character for avatar
  const avatarLetter = (username ?? "?").slice(0, 1).toUpperCase();

  return (
    <header
      className="sticky top-0 z-30 h-16 shrink-0 border-b"
      style={{
        background: "color-mix(in oklab, var(--surface) 80%, transparent)",
        backdropFilter: "blur(20px) saturate(1.6)",
        WebkitBackdropFilter: "blur(20px) saturate(1.6)",
        borderColor: "color-mix(in oklab, var(--line) 80%, transparent)",
      }}
    >
      <div className="h-full px-4 sm:px-6 flex items-center gap-3">
        {/* Mobile menu button */}
        <button
          onClick={onOpenMenu}
          className="lg:hidden p-2 -ml-1 rounded-xl transition-all hover:scale-105"
          style={{ color: "var(--ink-muted)", background: "var(--raised)" }}
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Logo + page title area */}
        <div className="lg:w-[17rem] lg:pr-4 shrink-0">
          <Wordmark subtitle="Behavioural risk" />
        </div>

        {/* Page title — desktop */}
        <div className="hidden lg:flex items-baseline gap-2 min-w-0">
          <h1
            className="text-sm font-bold truncate"
            style={{ color: "var(--ink)" }}
          >
            {current.label}
          </h1>
          <span
            className="text-xs truncate"
            style={{ color: "var(--ink-subtle)" }}
          >
            {current.hint}
          </span>
        </div>

        <div className="flex-1" />

        <StatusPill />
        <ThemeToggle compact />

        {/* User menu */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            className="flex items-center gap-2 pl-2 pr-1.5 py-1.5 rounded-xl transition-all max-w-[13rem] hover:scale-[1.02]"
            style={{
              border: "1px solid var(--line)",
              background: menuOpen
                ? "color-mix(in oklab, var(--brand) 8%, var(--raised))"
                : "var(--raised)",
              boxShadow: menuOpen
                ? "0 0 0 2px color-mix(in oklab, var(--brand) 25%, transparent)"
                : "none",
            }}
          >
            {/* Gradient avatar */}
            <span
              className="grid place-items-center h-7 w-7 rounded-full shrink-0 text-[11px] font-extrabold text-white"
              style={{
                background: "linear-gradient(135deg, var(--brand), var(--violet, #7c3aed))",
                boxShadow: "0 2px 8px var(--glow-brand, rgba(99,102,241,0.35))",
              }}
            >
              {avatarLetter}
            </span>
            <span
              className="hidden sm:block text-xs font-medium truncate font-mono"
              style={{ color: "var(--ink)" }}
            >
              {username}
            </span>
            <ChevronDown
              className="h-3.5 w-3.5 shrink-0 transition-transform duration-200"
              style={{
                color: "var(--ink-subtle)",
                transform: menuOpen ? "rotate(180deg)" : "rotate(0deg)",
              }}
            />
          </button>

          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 mt-2 w-72 rounded-2xl p-1.5 animate-scale-in"
              style={{
                background: "color-mix(in oklab, var(--surface) 95%, transparent)",
                backdropFilter: "blur(20px)",
                border: "1px solid var(--line)",
                boxShadow:
                  "0 4px 6px -1px rgba(0,0,0,0.1), 0 20px 60px -10px rgba(0,0,0,0.25), 0 0 0 1px color-mix(in oklab, var(--brand) 8%, transparent)",
              }}
            >
              {/* User info */}
              <div className="px-3 py-3">
                <div
                  className="text-[10px] font-bold uppercase tracking-[0.16em] mb-1"
                  style={{ color: "var(--ink-subtle)" }}
                >
                  Signed in as
                </div>
                <div
                  className="font-mono text-sm break-all font-semibold"
                  style={{ color: "var(--ink)" }}
                >
                  {username}
                </div>
                <div
                  className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed"
                >
                  {isUpiId ? (
                    <>
                      <BadgeCheck className="h-3.5 w-3.5 mt-px shrink-0" style={{ color: "var(--ok)" }} />
                      <span style={{ color: "var(--ink-muted)" }}>
                        Format and bank handle checked.
                      </span>
                    </>
                  ) : (
                    <>
                      <ShieldQuestion className="h-3.5 w-3.5 mt-px shrink-0" style={{ color: "var(--warn)" }} />
                      <span style={{ color: "var(--ink-muted)" }}>
                        Legacy username — payer-side matching cannot use it.
                      </span>
                    </>
                  )}
                </div>
              </div>

              <div className="h-px mx-1.5" style={{ background: "var(--line)" }} />

              <div className="px-3 py-2.5 flex items-center justify-between gap-3">
                <span className="text-xs" style={{ color: "var(--ink-muted)" }}>Theme</span>
                <ThemeToggle />
              </div>

              <div className="h-px mx-1.5" style={{ background: "var(--line)" }} />

              <button
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  setSettingsOpen(true);
                }}
                className="w-full flex items-start gap-2.5 px-3 py-2.5 rounded-xl text-sm text-left transition-all hover:scale-[1.01]"
                style={{ color: "var(--ink-muted)" }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background = "var(--raised)";
                  (e.currentTarget as HTMLButtonElement).style.color = "var(--ink)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                  (e.currentTarget as HTMLButtonElement).style.color = "var(--ink-muted)";
                }}
              >
                <Server className="h-4 w-4 mt-0.5 shrink-0" />
                <span className="min-w-0">
                  Backend server
                  <span
                    className="block text-[11px] truncate"
                    style={{ color: "var(--ink-subtle)" }}
                  >
                    {getStoredBackendUrl() ||
                      (isCapacitorNative() ? "not set" : "this site")}
                  </span>
                </span>
              </button>

              <div className="h-px mx-1.5" style={{ background: "var(--line)" }} />

              <button
                role="menuitem"
                onClick={logout}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm transition-all"
                style={{ color: "var(--danger)" }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background =
                    "color-mix(in oklab, var(--danger) 8%, transparent)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                }}
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>

      <BackendSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </header>
  );
};

export default AppHeader;
