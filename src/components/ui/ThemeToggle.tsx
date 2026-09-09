import React from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme, type ThemePreference } from "../../context/ThemeContext";

const OPTIONS: { id: ThemePreference; label: string; Icon: typeof Sun }[] = [
  { id: "light", label: "Light", Icon: Sun },
  { id: "dark", label: "Dark", Icon: Moon },
  { id: "system", label: "System", Icon: Monitor },
];

/** Three explicit states rather than a two-way switch.
 *
 * A plain toggle cannot express "follow my operating system", which is what
 * most people actually want; it silently pins them to whichever side they
 * last tapped.
 */
export const ThemeToggle: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const { preference, setPreference, cycle } = useTheme();

  if (compact) {
    const current = OPTIONS.find((o) => o.id === preference) ?? OPTIONS[2];
    const Icon = current.Icon;
    return (
      <button
        onClick={cycle}
        className="p-2 rounded-lg text-ink-muted hover:text-ink hover:bg-raised transition"
        aria-label={`Theme: ${current.label}. Click to change.`}
        title={`Theme: ${current.label}`}
      >
        <Icon className="h-[18px] w-[18px]" />
      </button>
    );
  }

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-raised border border-line"
    >
      {OPTIONS.map(({ id, label, Icon }) => {
        const active = preference === id;
        return (
          <button
            key={id}
            role="radio"
            aria-checked={active}
            onClick={() => setPreference(id)}
            title={label}
            className={`p-1.5 rounded-md transition ${
              active
                ? "bg-surface text-ink shadow-card"
                : "text-ink-subtle hover:text-ink-muted"
            }`}
          >
            <Icon className="h-4 w-4" />
            <span className="sr-only">{label}</span>
          </button>
        );
      })}
    </div>
  );
};

export default ThemeToggle;
