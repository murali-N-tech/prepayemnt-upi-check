import React, { useState } from "react";
import { 
  FileText, ShieldCheck, Cpu, Share2, AlertTriangle, 
  LineChart, Eye, Bell, Activity, Shield, Menu, X, LogOut, User 
} from "lucide-react";

import { useAuth } from "./context/AuthContext";
import { Login } from "./components/Auth/Login";
import { Register } from "./components/Auth/Register";

import StatementProfiling from "./components/StatementProfiling.tsx";
import PrePaymentRiskCheck from "./components/PrePaymentRiskCheck.tsx";
import FraudDetection from "./components/FraudDetection.tsx";
import NetworkGraph from "./components/NetworkGraph.tsx";
import FraudRings from "./components/FraudRings.tsx";
import FraudHeatmap from "./components/FraudHeatmap.tsx";
import Explainability from "./components/Explainability.tsx";
import FraudAlerts from "./components/FraudAlerts.tsx";
import SystemMonitor from "./components/SystemMonitor.tsx";
import UserProfile from "./components/UserProfile.tsx";

type PageID = 
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

export default function App() {
  const { isAuthenticated, logout, username } = useAuth();
  const [activePage, setActivePage] = useState<PageID>("User Profile");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  if (!isAuthenticated) {
    if (showRegister) {
      return <Register onSwitchToLogin={() => setShowRegister(false)} />;
    }
    return <Login onSwitchToRegister={() => setShowRegister(true)} />;
  }

  const menuItems = [
    { id: "User Profile", label: "User Profile", icon: User },
    { id: "Upload Statement", label: "Upload Statement", icon: FileText },
    { id: "Pre-Payment Risk Check", label: "Pre-Payment Risk Check", icon: ShieldCheck },
    { id: "Fraud Detection", label: "Fraud Detection", icon: Cpu },
    { id: "Fraud Network Graph", label: "Fraud Network Graph", icon: Share2 },
    { id: "Fraud Rings", label: "Fraud Rings", icon: AlertTriangle },
    { id: "Fraud Heatmap", label: "Fraud Heatmap", icon: LineChart },
    { id: "Explainability", label: "Explainability", icon: Eye },
    { id: "Fraud Alerts", label: "Fraud Alerts", icon: Bell },
    { id: "System Monitor", label: "System Monitor", icon: Activity },
  ] as const;

  const renderActivePage = () => {
    switch (activePage) {
      case "Upload Statement":
        return <StatementProfiling onNavigate={(page) => setActivePage(page as PageID)} />;
      case "User Profile":
        return <UserProfile />;
      case "Pre-Payment Risk Check":
        return <PrePaymentRiskCheck />;
      case "Fraud Detection":
        return <FraudDetection />;
      case "Fraud Network Graph":
        return <NetworkGraph />;
      case "Fraud Rings":
        return <FraudRings />;
      case "Fraud Heatmap":
        return <FraudHeatmap />;
      case "Explainability":
        return <Explainability />;
      case "Fraud Alerts":
        return <FraudAlerts />;
      case "System Monitor":
        return <SystemMonitor />;
    }
  };

  return (
    <div className="min-h-screen bg-[#0f172a] text-slate-100 flex flex-col font-sans" id="main-app-shell">
      
      {/* Upper Navigation bar */}
      <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-30 px-6 py-4 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-600/10 text-indigo-400 rounded-lg border border-indigo-500/20">
            <Shield className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
              Edge AI UPI Behaviour Risk System
            </h1>
            <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block font-mono">
              PRE-PAYMENT THREAT MITIGATION ENGINE
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="hidden md:flex items-center gap-2 text-sm text-slate-300 mr-2">
            <span className="h-2 w-2 rounded-full bg-green-500"></span>
            {username}
          </div>
          <button
            onClick={logout}
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Sign Out</span>
          </button>
          
          {/* Mobile menu triggers */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="lg:hidden p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition"
            aria-label="Toggle Navigation Menu"
          >
            {mobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </div>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row relative">
        
        {/* Left Navigation Menu Sidebar (Desktop) */}
        <aside className="hidden lg:block w-72 bg-slate-900 border-r border-slate-800 p-6 space-y-2 shrink-0">
          <div className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-4 px-3">
            Analytic Modules
          </div>
          <nav className="space-y-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              const isActive = activePage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActivePage(item.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${
                    isActive 
                      ? "bg-indigo-600/10 text-indigo-400 border border-indigo-500/20" 
                      : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200 border border-transparent"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Floating Side Drawer (Mobile Overlay) */}
        {mobileMenuOpen && (
          <div className="lg:hidden fixed inset-0 z-20 bg-slate-950/80 backdrop-blur-sm">
            <aside className="w-72 h-full bg-slate-900 p-6 flex flex-col justify-between">
              <div className="space-y-6">
                <div className="flex justify-between items-center pb-4 border-b border-slate-800">
                  <span className="text-xs text-slate-500 font-semibold uppercase tracking-wider">
                    Analytic Modules
                  </span>
                  <button
                    onClick={() => setMobileMenuOpen(false)}
                    className="p-1 text-slate-400 hover:text-white hover:bg-slate-800 rounded"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <nav className="space-y-1">
                  {menuItems.map((item) => {
                    const Icon = item.icon;
                    const isActive = activePage === item.id;
                    return (
                      <button
                        key={item.id}
                        onClick={() => {
                          setActivePage(item.id);
                          setMobileMenuOpen(false);
                        }}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${
                          isActive 
                            ? "bg-indigo-600/10 text-indigo-400 border border-indigo-500/20" 
                            : "text-slate-400 hover:bg-slate-800/40 hover:text-slate-200 border border-transparent"
                        }`}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </button>
                    );
                  })}
                </nav>
              </div>

              <div className="text-[10px] text-slate-600 font-mono text-center">
                Edge UPI Secure Guard v1.0.0
              </div>
            </aside>
          </div>
        )}

        {/* Core Main Panel Frame */}
        <main className="flex-1 p-6 md:p-8 lg:p-10 max-w-7xl mx-auto w-full overflow-y-auto">
          {renderActivePage()}
        </main>
      </div>
    </div>
  );
}
