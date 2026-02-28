"use client";

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("Invalid reset link. Please request a new one.");
    }
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
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

    setLoading(true);
    try {
      const data = await api.post<{
        status: string;
        access_token?: string;
        totp_required?: boolean;
      }>("/api/auth/reset-password", {
        token,
        new_password: newPw,
      });

      // Store the JWT so AuthGate auto-loads the user when we redirect
      if (data.access_token) {
        localStorage.setItem("token", data.access_token);
      }

      setSuccess(true);
      // Short pause to show the success message, then enter the app
      setTimeout(() => router.push("/"), 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Reset failed. The link may have expired.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm rounded-xl border border-card-border bg-card-bg p-8">
        <Logo />

        {success ? (
          <>
            <div className="mb-4 flex flex-col items-center gap-2">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/20 text-2xl">✅</div>
              <h2 className="text-sm font-semibold">Password Updated</h2>
            </div>
            <p className="text-center text-xs text-muted mb-4">
              Your password has been updated. Logging you in…
            </p>
            <button onClick={() => router.push("/")} className={btnCls}>
              Go to Dashboard
            </button>
          </>
        ) : (
          <>
            <h2 className="text-center text-sm font-semibold mb-1">Set New Password</h2>
            <p className="text-center text-xs text-muted mb-4">
              Choose a strong password for your account.
            </p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs text-muted mb-1.5">New Password</label>
                <input
                  type="password"
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  className={inputCls}
                  placeholder="Min. 6 characters"
                  required
                  autoFocus
                  disabled={!token}
                />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1.5">Confirm Password</label>
                <input
                  type="password"
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  className={inputCls}
                  required
                  disabled={!token}
                />
              </div>

              {error && <p className="text-xs text-danger">{error}</p>}

              <button type="submit" className={btnCls} disabled={loading || !token}>
                {loading ? "Updating…" : "Set New Password"}
              </button>
            </form>

            <p className="mt-4 text-center text-xs text-muted">
              <button onClick={() => router.push("/")} className="text-accent hover:underline">
                Back to Sign In
              </button>
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-muted text-sm">Loading…</div>
      </div>
    }>
      <ResetPasswordForm />
    </Suspense>
  );
}
