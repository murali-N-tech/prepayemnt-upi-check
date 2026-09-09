import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type ThemePreference = "light" | "dark" | "system";
type Resolved = "light" | "dark";

interface ThemeContextType {
  /** What the user chose, including "follow the OS". */
  preference: ThemePreference;
  /** What is actually on screen right now. */
  theme: Resolved;
  setPreference: (next: ThemePreference) => void;
  /** Light -> dark -> follow the OS -> light. */
  cycle: () => void;
}

const STORAGE_KEY = "theme";
const ThemeContext = createContext<ThemeContextType | null>(null);

function systemTheme(): Resolved {
  if (typeof window === "undefined" || !window.matchMedia) return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function storedPreference(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    // Private mode or blocked storage - fall back to the OS setting.
  }
  return "system";
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [preference, setPreferenceState] = useState<ThemePreference>(storedPreference);
  const [system, setSystem] = useState<Resolved>(systemTheme);

  // Track the OS setting even when it is not the active preference, so
  // switching back to "system" is instant rather than one frame late.
  useEffect(() => {
    if (!window.matchMedia) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSystem(e.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const theme: Resolved = preference === "system" ? system : preference;

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
  }, [theme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The choice still applies to this tab.
    }
  }, []);

  const cycle = useCallback(() => {
    setPreference(
      preference === "light" ? "dark" : preference === "dark" ? "system" : "light"
    );
  }, [preference, setPreference]);

  const value = useMemo(
    () => ({ preference, theme, setPreference, cycle }),
    [preference, theme, setPreference, cycle]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within a ThemeProvider");
  return context;
};
