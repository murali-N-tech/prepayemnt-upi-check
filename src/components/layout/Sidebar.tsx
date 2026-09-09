import React from "react";
import { X } from "lucide-react";
import { NAV_GROUPS, type PageID } from "./nav";
import { Wordmark } from "../ui/Logo";

interface SidebarProps {
  activePage: PageID;
  onNavigate: (page: PageID) => void;
}

const NavList: React.FC<SidebarProps> = ({ activePage, onNavigate }) => (
  <nav className="space-y-6">
    {NAV_GROUPS.map((group) => (
      <div key={group.title}>
        <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-subtle">
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
                className={`group relative w-full flex items-start gap-3 pl-3 pr-2 py-2 rounded-lg text-left transition ${
                  active
                    ? "bg-brand/10 text-brand"
                    : "text-ink-muted hover:bg-raised hover:text-ink"
                }`}
              >
                {/* The active marker is a rail, not a border, so the row does
                    not shift by a pixel when it becomes active. */}
                <span
                  className={`absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full transition ${
                    active ? "bg-brand" : "bg-transparent"
                  }`}
                />
                <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${active ? "text-brand" : "text-ink-subtle group-hover:text-ink-muted"}`} />
                <span className="min-w-0">
                  <span className="block text-sm font-medium leading-tight">{item.label}</span>
                  <span className="block text-[11px] leading-tight text-ink-subtle mt-0.5 truncate">
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
  <aside className="hidden lg:flex flex-col w-72 shrink-0 border-r border-line bg-surface">
    <div className="flex-1 overflow-y-auto p-4">
      <NavList {...props} />
    </div>
    <div className="p-4 border-t border-line">
      <p className="text-[11px] leading-relaxed text-ink-subtle">
        Checks run before the payment leaves. Nothing here moves money.
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
        className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className="relative h-full w-[19rem] max-w-[85vw] bg-surface border-r border-line flex flex-col animate-fade-in">
        <div className="flex items-center justify-between p-4 border-b border-line">
          <Wordmark compact subtitle="Risk intelligence" />
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-ink-muted hover:text-ink hover:bg-raised transition"
            aria-label="Close menu"
          >
            <X className="h-5 w-5" />
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
