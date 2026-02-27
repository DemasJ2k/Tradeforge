"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useSettings } from "@/hooks/useSettings";
import { api } from "@/lib/api";

const inputCls =
  "w-full rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent";
const btnCls =
  "w-full rounded-lg bg-accent py-2.5 text-sm font-medium text-black hover:bg-accent-hover transition-colors";

function Logo() {
  return (
    <div className="mb-6 flex items-center justify-center gap-2">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-black font-bold">
        TF
      </div>
      <span className="text-xl font-semibold">TradeForge</span>
    </div>
  );
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, login, register, loadUser, mustChangePassword, totpRequired, clearFlags, refreshUser } = useAuth();
  const { loadSettings } = useSettings();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  // Force change password state
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");

  // TOTP verification state
  const [totpCode, setTotpCode] = useState("");

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  // Load and apply settings (theme, accent, font) once user is fully authenticated
  useEffect(() => {
    if (user && !mustChangePassword && !totpRequired) {
      loadSettings();
      // Auto-connect brokers that have auto_connect=True
      api.post("/api/settings/broker-auto-connect").catch(() => {});
    }
  }, [user, mustChangePassword, totpRequired, loadSettings]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-muted text-sm">Loading...</div>
      </div>
    );
  }

  // ─── Forced Password Change Screen ───
  if (user && mustChangePassword) {
    const handleChangePw = async (e: React.FormEvent) => {
      e.preventDefault();
      setError("");
      if (newPw.length < 6) {
        setError("Password must be at least 6 characters");
        return;
      }
      if (newPw !== confirmPw) {
        setError("Passwords do not match");
        return;
      }
      try {
        await api.post("/api/auth/force-change-password", { new_password: newPw });
        clearFlags();
        await refreshUser();
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to change password");
      }
    };

    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm rounded-xl border border-card-border bg-card-bg p-8">
          <Logo />
          <h2 className="text-center text-sm font-semibold mb-1">Change Your Password</h2>
          <p className="text-center text-xs text-muted mb-4">
            You must set a new password before continuing.
          </p>
          <form onSubmit={handleChangePw} className="space-y-4">
            <div>
              <label className="block text-xs text-muted mb-1.5">New Password</label>
              <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} className={inputCls} required />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1.5">Confirm Password</label>
              <input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} className={inputCls} required />
            </div>
            {error && <p className="text-xs text-danger">{error}</p>}
            <button type="submit" className={btnCls}>Set New Password</button>
          </form>
        </div>
      </div>
    );
  }

  // ─── TOTP Verification Screen ───
  if (user && totpRequired) {
    const handleTotp = async (e: React.FormEvent) => {
      e.preventDefault();
      setError("");
      try {
        const resp = await api.post<{ valid: boolean }>("/api/auth/verify-totp", { code: totpCode });
        if (resp.valid) {
          clearFlags();
        } else {
          setError("Invalid code. Try again.");
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Verification failed");
      }
    };

    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm rounded-xl border border-card-border bg-card-bg p-8">
          <Logo />
          <h2 className="text-center text-sm font-semibold mb-1">Two-Factor Authentication</h2>
          <p className="text-center text-xs text-muted mb-4">
            Enter the 6-digit code from your authenticator app.
          </p>
          <form onSubmit={handleTotp} className="space-y-4">
            <input
              type="text"
              inputMode="numeric"
              maxLength={6}
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
              className={inputCls + " text-center text-lg tracking-[0.5em]"}
              placeholder="000000"
              autoFocus
              required
            />
            {error && <p className="text-xs text-danger">{error}</p>}
            <button type="submit" className={btnCls}>Verify</button>
          </form>
        </div>
      </div>
    );
  }

  // ─── Login / Register Screen ───
  if (!user) {
    const handleSubmit = async (e: React.FormEvent) => {
      e.preventDefault();
      setError("");
      try {
        if (mode === "login") {
          await login(username, password);
        } else {
          await register(username, password);
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Something went wrong");
      }
    };

    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="w-full max-w-sm rounded-xl border border-card-border bg-card-bg p-8">
          <Logo />

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-muted mb-1.5">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className={inputCls}
                required
              />
            </div>
            <div>
              <label className="block text-xs text-muted mb-1.5">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
                required
              />
            </div>

            {error && <p className="text-xs text-danger">{error}</p>}

            <button type="submit" className={btnCls}>
              {mode === "login" ? "Sign In" : "Create Account"}
            </button>
          </form>

          <p className="mt-4 text-center text-xs text-muted">
            {mode === "login" ? (
              <>
                Have an invitation?{" "}
                <button
                  onClick={() => { setMode("register"); setError(""); }}
                  className="text-accent hover:underline"
                >
                  Register
                </button>
              </>
            ) : (
              <>
                Have an account?{" "}
                <button
                  onClick={() => { setMode("login"); setError(""); }}
                  className="text-accent hover:underline"
                >
                  Sign in
                </button>
              </>
            )}
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
