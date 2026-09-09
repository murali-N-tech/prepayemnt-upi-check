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
      ? { dot: "bg-ink-faint", text: "Checking", detail: "Contacting the server" }
      : health.status === "ok"
      ? { dot: "bg-ok", text: "All services up", detail: "Express, Python and the model are ready" }
      : {
          dot: "bg-warn",
          text: "Degraded",
          detail:
            health.model_detail ??
            `backend: ${health.backend}, model: ${health.model}`,
        };

  return (
    <span
      title={tone.detail}
      className="hidden md:inline-flex items-center gap-2 px-2.5 py-1 rounded-full border border-line bg-raised text-xs text-ink-muted"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
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

  return (
    <header className="sticky top-0 z-30 h-16 shrink-0 border-b border-line bg-surface/85 backdrop-blur-md">
      <div className="h-full px-4 sm:px-6 flex items-center gap-3">
        <button
          onClick={onOpenMenu}
          className="lg:hidden p-2 -ml-1 rounded-lg text-ink-muted hover:text-ink hover:bg-raised transition"
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        <div className="lg:w-[17rem] lg:pr-4 shrink-0">
          <Wordmark subtitle="Behavioural risk" />
        </div>

        {/* On desktop the sidebar already names the section, so the header
            carries the current page instead of repeating the product name. */}
        <div className="hidden lg:flex items-baseline gap-2 min-w-0">
          <h1 className="text-sm font-semibold text-ink truncate">{current.label}</h1>
          <span className="text-xs text-ink-subtle truncate">{current.hint}</span>
        </div>

        <div className="flex-1" />

        <StatusPill />
        <ThemeToggle compact />

        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            className="flex items-center gap-2 pl-2 pr-1.5 py-1.5 rounded-lg border border-line bg-raised hover:bg-surface transition max-w-[13rem]"
          >
            <span className="grid place-items-center h-6 w-6 rounded-full bg-brand/15 text-brand text-[11px] font-bold shrink-0">
              {(username ?? "?").slice(0, 1).toUpperCase()}
            </span>
            <span className="hidden sm:block text-xs font-medium text-ink truncate font-mono">
              {username}
            </span>
            <ChevronDown className="h-3.5 w-3.5 text-ink-subtle shrink-0" />
          </button>

          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 mt-2 w-72 rounded-xl border border-line bg-surface shadow-lift p-1.5 animate-fade-in"
            >
              <div className="px-3 py-2.5">
                <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-subtle">
                  Signed in as
                </div>
                <div className="mt-1 font-mono text-sm text-ink break-all">{username}</div>
                <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed">
                  {isUpiId ? (
                    <>
                      <BadgeCheck className="h-3.5 w-3.5 mt-px text-ok shrink-0" />
                      <span className="text-ink-muted">
                        Format and bank handle checked. The account itself is only
                        verified against the payment network when a provider is
                        configured.
                      </span>
                    </>
                  ) : (
                    <>
                      <ShieldQuestion className="h-3.5 w-3.5 mt-px text-warn shrink-0" />
                      <span className="text-ink-muted">
                        This is a legacy username, not a UPI ID, so payer-side
                        matching cannot use it.
                      </span>
                    </>
                  )}
                </div>
              </div>

              <div className="my-1 h-px bg-line" />

              <div className="px-3 py-2 flex items-center justify-between gap-3">
                <span className="text-xs text-ink-muted">Theme</span>
                <ThemeToggle />
              </div>

              <div className="my-1 h-px bg-line" />

              <button
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  setSettingsOpen(true);
                }}
                className="w-full flex items-start gap-2 px-3 py-2 rounded-lg text-sm text-ink-muted hover:text-ink hover:bg-raised transition text-left"
              >
                <Server className="h-4 w-4 mt-0.5 shrink-0" />
                <span className="min-w-0">
                  Backend server
                  <span className="block text-[11px] text-ink-subtle truncate">
                    {getStoredBackendUrl() ||
                      (isCapacitorNative() ? "not set" : "this site")}
                  </span>
                </span>
              </button>

              <div className="my-1 h-px bg-line" />

              <button
                role="menuitem"
                onClick={logout}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-ink-muted hover:text-ink hover:bg-raised transition"
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
