import React, { useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { AuthShell, fieldClass, labelClass, submitClass, submitStyle } from "./AuthShell";
import { getApiUrl } from "../../services/apiConfig";

export const Login: React.FC<{
  onSwitchToRegister: () => void;
  onBack?: () => void;
}> = ({ onSwitchToRegister, onBack }) => {
  const [upiId, setUpiId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const response = await fetch(getApiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // The server identifies accounts by UPI ID; `username` is the wire
        // field name it has always used.
        body: JSON.stringify({ username: upiId.trim().toLowerCase(), password }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Login failed");

      login(data.token, data.user_id, data.upi_id || data.username);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in with the UPI ID you pay from."
      onBack={onBack}
      footer={
        <>
          Don't have an account?{" "}
          <button
            onClick={onSwitchToRegister}
            className="font-semibold text-brand hover:underline"
          >
            Create one
          </button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-danger/30 bg-danger/10 px-3.5 py-2.5 text-sm text-danger"
          >
            {error}
          </div>
        )}

        <div>
          <label htmlFor="login-upi" className={labelClass}>
            UPI ID
          </label>
          <input
            id="login-upi"
            type="text"
            required
            autoComplete="username"
            spellCheck={false}
            autoCapitalize="none"
            value={upiId}
            onChange={(e) => setUpiId(e.target.value)}
            className={`${fieldClass()} font-mono`}
            placeholder="yourname@bank"
          />
        </div>

        <div>
          <label htmlFor="login-password" className={labelClass}>
            Password
          </label>
          <input
            id="login-password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={fieldClass()}
            placeholder="Enter your password"
          />
        </div>

        <button type="submit" disabled={loading} className={submitClass} style={submitStyle}>
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </AuthShell>
  );
};
