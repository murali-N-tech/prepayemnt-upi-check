import React, { useMemo, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { UpiStatusNote, useUpiStatus } from "./UpiStatusNote";
import { AuthShell, fieldClass, labelClass, submitClass } from "./AuthShell";

/** Same shape the server enforces, so the obvious mistakes are caught here. */
const VPA_PATTERN = /^[a-z0-9.\-_]{2,256}@[a-z][a-z0-9.\-_]{1,63}$/;

export const Register: React.FC<{
  onSwitchToLogin: () => void;
  onBack?: () => void;
}> = ({ onSwitchToLogin, onBack }) => {
  const [upiId, setUpiId] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const upiStatus = useUpiStatus();

  const normalised = useMemo(() => upiId.trim().toLowerCase(), [upiId]);
  const shapeOk = VPA_PATTERN.test(normalised);
  const showShapeHint = normalised.length > 0 && !shapeOk;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!shapeOk) {
      setError("Enter a UPI ID in the form yourname@bank.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: normalised, password }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Registration failed");

      login(data.token, data.user_id, data.upi_id || data.username);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      title="Create your account"
      subtitle="Your UPI ID is your account — it is what the payer-side checks read."
      onBack={onBack}
      footer={
        <>
          Already have an account?{" "}
          <button onClick={onSwitchToLogin} className="font-semibold text-brand hover:underline">
            Sign in
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
          <label htmlFor="register-upi" className={labelClass}>
            UPI ID
          </label>
          <input
            id="register-upi"
            type="text"
            required
            autoComplete="username"
            spellCheck={false}
            autoCapitalize="none"
            value={upiId}
            onChange={(e) => setUpiId(e.target.value)}
            className={`${fieldClass(showShapeHint)} font-mono`}
            placeholder="yourname@bank"
            aria-invalid={showShapeHint}
          />
          {showShapeHint ? (
            <p className="mt-2 text-xs text-warn leading-relaxed">
              A UPI ID looks like <span className="font-mono">yourname@okaxis</span> — a
              name, an @, then your bank's handle.
            </p>
          ) : (
            <UpiStatusNote status={upiStatus} />
          )}
        </div>

        <div>
          <label htmlFor="register-password" className={labelClass}>
            Password
          </label>
          <input
            id="register-password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={fieldClass()}
            placeholder="At least 8 characters"
          />
        </div>

        <div>
          <label htmlFor="register-confirm" className={labelClass}>
            Confirm password
          </label>
          <input
            id="register-confirm"
            type="password"
            required
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className={fieldClass(confirmPassword.length > 0 && confirmPassword !== password)}
            placeholder="Repeat it"
          />
        </div>

        <button type="submit" disabled={loading} className={submitClass}>
          {loading ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthShell>
  );
};
