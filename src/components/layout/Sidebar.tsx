import React from "react";
import { X } from "lucide-react";
import { NAV_GROUPS, type PageID } from "./nav";
import { Wordmark } from "../ui/Logo";

interface SidebarProps {
  activePage: PageID;
  onNavigate: (page: PageID) => void;
}

const NavList: React.FC<SidebarProps> = ({ activePage, onNavigate }) => (
  <nav className="space-y-5">
    {NAV_GROUPS.map((group) => (
      <div key={group.title}>
        <div
          className="px-3 mb-2 text-[9px] font-bold uppercase tracking-[0.18em]"
          style={{ color: "var(--ink-faint)" }}
        >
          {group.title}
        </div>
        <div className="space-y-0.5">
          {group.items.map((item) => {
            const Icon = item.icon;
            const active = activePage === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                aria-current={active ? "page" : undefined}
                className="group relative w-full flex items-start gap-3 pl-3 pr-2 py-2.5 rounded-xl text-left transition-all duration-200"
                style={
                  active
                    ? {
                        background:
                          "linear-gradient(135deg, color-mix(in oklab, var(--brand) 14%, transparent), color-mix(in oklab, var(--violet, #7c3aed) 10%, transparent))",
                        color: "var(--brand)",
                        boxShadow: "0 2px 12px color-mix(in oklab, var(--brand) 12%, transparent)",
                        border: "1px solid color-mix(in oklab, var(--brand) 22%, transparent)",
                      }
                    : {
                        color: "var(--ink-muted)",
                        border: "1px solid transparent",
                      }
                }
                onMouseEnter={(e) => {
                  if (!active) {
                    (e.currentTarget as HTMLButtonElement).style.background =
                      "color-mix(in oklab, var(--raised) 100%, transparent)";
                    (e.currentTarget as HTMLButtonElement).style.color = "var(--ink)";
                    (e.currentTarget as HTMLButtonElement).style.border =
                      "1px solid var(--line)";
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateX(2px)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                    (e.currentTarget as HTMLButtonElement).style.color = "var(--ink-muted)";
                    (e.currentTarget as HTMLButtonElement).style.border = "1px solid transparent";
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateX(0)";
                  }
                }}
              >
                {/* Active gradient left rail */}
                {active && (
                  <span
                    className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full"
                    style={{
                      background:
                        "linear-gradient(to bottom, var(--brand), var(--violet, #7c3aed))",
                    }}
                  />
                )}

                {/* Icon */}
                <span
                  className="grid place-items-center h-6 w-6 rounded-lg shrink-0 mt-0.5 transition-all duration-200"
                  style={
                    active
                      ? {
                          background:
                            "linear-gradient(135deg, var(--brand), var(--violet, #7c3aed))",
                          color: "#fff",
                          boxShadow: "0 2px 8px var(--glow-brand, rgba(99,102,241,0.35))",
                        }
                      : {
                          background: "var(--raised)",
                          color: "var(--ink-subtle)",
                        }
                  }
                >
                  <Icon className="h-3.5 w-3.5" />
                </span>

                <span className="min-w-0">
                  <span
                    className="block text-sm font-semibold leading-tight"
                    style={active ? { color: "var(--brand)" } : {}}
                  >
                    {item.label}
                  </span>
                  <span
                    className="block text-[10px] leading-tight mt-0.5 truncate"
                    style={{ color: active ? "var(--brand-light, var(--brand))" : "var(--ink-subtle)", opacity: active ? 0.8 : 1 }}
                  >
                    {item.hint}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    ))}
  </nav>
);

export const Sidebar: React.FC<SidebarProps> = (props) => (
  <aside
    className="hidden lg:flex flex-col w-72 shrink-0 border-r"
    style={{
      background: "color-mix(in oklab, var(--surface) 85%, transparent)",
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
      borderColor: "var(--line)",
    }}
  >
    <div className="flex-1 overflow-y-auto p-4 pt-5">
      <NavList {...props} />
    </div>
    <div
      className="p-4 m-3 rounded-xl"
      style={{
        background:
          "linear-gradient(135deg, color-mix(in oklab, var(--brand) 8%, transparent), color-mix(in oklab, var(--violet, #7c3aed) 6%, transparent))",
        border: "1px solid color-mix(in oklab, var(--brand) 15%, transparent)",
      }}
    >
      <p
        className="text-[10px] leading-relaxed font-medium"
        style={{ color: "var(--ink-subtle)" }}
      >
        ⚡ Checks run{" "}
        <span style={{ color: "var(--brand)", fontWeight: 600 }}>before</span> the payment
        leaves. Nothing here moves money.
      </p>
    </div>
  </aside>
);

export const MobileSidebar: React.FC<SidebarProps & { open: boolean; onClose: () => void }> = ({
  open,
  onClose,
  activePage,
  onNavigate,
}) => {
  if (!open) return null;
  return (
    <div className="lg:hidden fixed inset-0 z-40">
      <div
        className="absolute inset-0 backdrop-blur-sm"
        style={{ background: "rgba(5, 8, 26, 0.7)" }}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className="relative h-full w-[19rem] max-w-[85vw] flex flex-col animate-fade-in border-r"
        style={{
          background: "color-mix(in oklab, var(--surface) 95%, transparent)",
          backdropFilter: "blur(20px)",
          borderColor: "var(--line)",
        }}
      >
        <div className="flex items-center justify-between p-4 border-b" style={{ borderColor: "var(--line)" }}>
          <Wordmark compact subtitle="Risk intelligence" />
          <button
            onClick={onClose}
            className="p-2 rounded-xl transition hover:scale-110"
            style={{ color: "var(--ink-muted)", background: "var(--raised)" }}
            aria-label="Close menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <NavList
            activePage={activePage}
            onNavigate={(page) => {
              onNavigate(page);
              onClose();
            }}
          />
        </div>
      </aside>
    </div>
  );
};
