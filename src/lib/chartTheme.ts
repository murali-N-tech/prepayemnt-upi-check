import { useTheme } from "../context/ThemeContext";

/** Colours for anything drawn rather than styled — Recharts, and the SVG in
 *  the network graph.
 *
 *  Charts take colours as props, not classes, so they cannot follow the CSS
 *  tokens on their own. Hardcoding a dark palette left every grid line and
 *  node label invisible the moment the page went light. These values mirror
 *  the tokens in index.css.
 */
export interface ChartTheme {
  grid: string;
  axis: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  /** Categorical series, ordered so neighbours stay distinguishable. */
  series: string[];
  brand: string;
  danger: string;
  warn: string;
  ok: string;
  /** Fills for the network graph. */
  nodeLabel: string;
  nodeStroke: string;
  edge: string;
}

const DARK: ChartTheme = {
  grid: "#1e293b",
  axis: "#64748b",
  tooltipBg: "#1e293b",
  tooltipBorder: "#334155",
  tooltipText: "#f8fafc",
  series: ["#818cf8", "#a78bfa", "#38bdf8", "#34d399", "#fbbf24", "#fb7185", "#c4b5fd", "#5eead4", "#f0abfc", "#93c5fd"],
  brand: "#818cf8",
  danger: "#fb7185",
  warn: "#fbbf24",
  ok: "#34d399",
  nodeLabel: "#f1f5f9",
  nodeStroke: "#0f172a",
  edge: "#334155",
};

const LIGHT: ChartTheme = {
  grid: "#e3e8ef",
  axis: "#6b7a90",
  tooltipBg: "#ffffff",
  tooltipBorder: "#e3e8ef",
  tooltipText: "#0b1220",
  series: ["#4f46e5", "#7c3aed", "#0284c7", "#047857", "#b45309", "#dc2626", "#6d28d9", "#0f766e", "#a21caf", "#1d4ed8"],
  brand: "#4f46e5",
  danger: "#dc2626",
  warn: "#b45309",
  ok: "#047857",
  nodeLabel: "#0b1220",
  nodeStroke: "#ffffff",
  edge: "#cbd5e1",
};

export function useChartTheme(): ChartTheme {
  return useTheme().theme === "dark" ? DARK : LIGHT;
}

/** Recharts <Tooltip> takes plain style objects. */
export function tooltipProps(t: ChartTheme) {
  return {
    contentStyle: {
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      borderRadius: "8px",
      fontSize: "12px",
      color: t.tooltipText,
    },
    labelStyle: { color: t.tooltipText },
    itemStyle: { color: t.tooltipText },
  };
}
