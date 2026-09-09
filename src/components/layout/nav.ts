import {
  Activity,
  AlertTriangle,
  Bell,
  Cpu,
  Eye,
  FileText,
  LineChart,
  ScanLine,
  Share2,
  ShieldCheck,
  User,
} from "lucide-react";

export type PageID =
  | "Check a Payee"
  | "Upload Statement"
  | "User Profile"
  | "Pre-Payment Risk Check"
  | "Fraud Detection"
  | "Fraud Network Graph"
  | "Fraud Rings"
  | "Fraud Heatmap"
  | "Explainability"
  | "Fraud Alerts"
  | "System Monitor";

export interface NavItem {
  id: PageID;
  label: string;
  icon: typeof ScanLine;
  /** Shown under the label in the sidebar, so a stranger can tell the eleven
   *  screens apart without clicking each one. */
  hint: string;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

/** Eleven flat menu entries is a list, not a structure. Grouping them by the
 *  question each screen answers is what makes the app navigable. */
export const NAV_GROUPS: NavGroup[] = [
  {
    title: "Before you pay",
    items: [
      {
        id: "Check a Payee",
        label: "Check a Payee",
        icon: ScanLine,
        hint: "Scan a QR or paste a UPI ID",
      },
      {
        id: "Pre-Payment Risk Check",
        label: "Pre-Payment Check",
        icon: ShieldCheck,
        hint: "Score a payment against your habits",
      },
    ],
  },
  {
    title: "Your account",
    items: [
      { id: "User Profile", label: "Behaviour Profile", icon: User, hint: "What the system knows about you" },
      { id: "Upload Statement", label: "Upload Statement", icon: FileText, hint: "Build the profile from a PDF or CSV" },
    ],
  },
  {
    title: "Investigate",
    items: [
      { id: "Fraud Detection", label: "Transaction Scoring", icon: Cpu, hint: "Run the model on one transaction" },
      { id: "Fraud Network Graph", label: "Network Graph", icon: Share2, hint: "Who pays whom" },
      { id: "Fraud Rings", label: "Fraud Rings", icon: AlertTriangle, hint: "Payees sharing one-shot payers" },
      { id: "Fraud Heatmap", label: "Risk Heatmap", icon: LineChart, hint: "Where risk concentrates" },
      { id: "Explainability", label: "Explainability", icon: Eye, hint: "Why the model decided that" },
    ],
  },
  {
    title: "Operations",
    items: [
      { id: "Fraud Alerts", label: "Alerts", icon: Bell, hint: "Recent high-risk activity" },
      { id: "System Monitor", label: "System Monitor", icon: Activity, hint: "Both services and the model" },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

export function navItem(id: PageID): NavItem {
  return ALL_NAV_ITEMS.find((item) => item.id === id) ?? ALL_NAV_ITEMS[0];
}
