import { useState } from "react";

import { useAuth } from "./context/AuthContext";
import { Login } from "./components/Auth/Login";
import { Register } from "./components/Auth/Register";
import Landing from "./components/Landing";
import AppHeader from "./components/layout/AppHeader";
import { MobileSidebar, Sidebar } from "./components/layout/Sidebar";
import { navItem, type PageID } from "./components/layout/nav";
import ErrorBoundary from "./components/ui/ErrorBoundary";

import PayeeCheck from "./components/PayeeCheck.tsx";
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

/** What a signed-out visitor is looking at. */
type PublicView = "landing" | "login" | "register";

export default function App() {
  const { isAuthenticated, isLoading } = useAuth();
  const [activePage, setActivePage] = useState<PageID>("Check a Payee");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [publicView, setPublicView] = useState<PublicView>("landing");

  if (isLoading) {
    return (
      <div className="min-h-screen bg-canvas flex items-center justify-center">
        <div className="h-8 w-8 border-2 border-brand border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    if (publicView === "login") {
      return (
        <Login
          onSwitchToRegister={() => setPublicView("register")}
          onBack={() => setPublicView("landing")}
        />
      );
    }
    if (publicView === "register") {
      return (
        <Register
          onSwitchToLogin={() => setPublicView("login")}
          onBack={() => setPublicView("landing")}
        />
      );
    }
    return (
      <Landing
        onSignIn={() => setPublicView("login")}
        onCreateAccount={() => setPublicView("register")}
      />
    );
  }

  const renderActivePage = () => {
    switch (activePage) {
      case "Check a Payee":
        return <PayeeCheck />;
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

  const current = navItem(activePage);

  return (
    <div className="min-h-screen bg-canvas text-ink font-sans flex flex-col" id="main-app-shell">
      <AppHeader activePage={activePage} onOpenMenu={() => setMobileMenuOpen(true)} />

      <div className="flex-1 flex min-h-0">
        <Sidebar activePage={activePage} onNavigate={setActivePage} />
        <MobileSidebar
          open={mobileMenuOpen}
          onClose={() => setMobileMenuOpen(false)}
          activePage={activePage}
          onNavigate={setActivePage}
        />

        <main className="flex-1 min-w-0">
          {/* On small screens the header has no room for the page title, so
              it lives here instead of disappearing. */}
          <div className="lg:hidden px-4 sm:px-6 pt-6">
            <h1 className="text-xl font-bold tracking-tight text-ink">{current.label}</h1>
            <p className="text-sm text-ink-subtle">{current.hint}</p>
          </div>

          <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full">
            <div key={activePage} className="animate-fade-in">
              <ErrorBoundary resetKey={activePage}>{renderActivePage()}</ErrorBoundary>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
