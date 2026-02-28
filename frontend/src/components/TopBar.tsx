"use client";

import { useEffect, useState, useRef } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useSidebar } from "@/hooks/useSidebar";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";

const fmtBalance = (n: number, currency: string) => {
  const k = Math.abs(n) >= 1_000_000
    ? `${(n / 1_000_000).toFixed(2)}M`
    : Math.abs(n) >= 1_000
    ? `${(n / 1_000).toFixed(1)}k`
    : n.toFixed(2);
  return `${currency} ${k}`;
};

export default function TopBar() {
  const { user, logout } = useAuth();
  const { toggle } = useSidebar();
  const { accounts, activeBroker, setActiveBroker, refreshAccounts } = useBrokerAccounts();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Ctrl+B global shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "b") {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggle]);

  // Poll broker accounts every 15 seconds
  useEffect(() => {
    refreshAccounts();
    const interval = setInterval(refreshAccounts, 15_000);
    return () => clearInterval(interval);
  }, [refreshAccounts]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const activeAccount = accounts.find((a) => a.broker === activeBroker);
  const connectedCount = accounts.length;

  return (
    <header className="flex h-14 items-center justify-between border-b border-card-border bg-sidebar-bg px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-medium text-foreground">Dashboard</h1>
      </div>

      <div className="flex items-center gap-3">
        {/* Broker account switcher */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen((o) => !o)}
            className="flex items-center gap-2 rounded-lg bg-card-bg px-3 py-1.5 text-xs hover:bg-sidebar-hover transition-colors"
          >
            <div
              className={`h-2 w-2 rounded-full shrink-0 ${
                connectedCount > 0 ? "bg-green-400" : "bg-muted"
              }`}
            />
            {activeAccount ? (
              <>
                <span className="font-medium capitalize text-foreground">
                  {activeAccount.broker}
                </span>
                <span className="text-muted">
                  {fmtBalance(activeAccount.balance, activeAccount.currency)}
                </span>
                {connectedCount > 1 && (
                  <span className="ml-1 rounded-full bg-accent/20 px-1.5 py-0.5 text-[10px] text-accent">
                    +{connectedCount - 1}
                  </span>
                )}
              </>
            ) : (
              <span className="text-muted">No broker connected</span>
            )}
            {connectedCount > 0 && (
              <svg className="h-3 w-3 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            )}
          </button>

          {dropdownOpen && connectedCount > 0 && (
            <div className="absolute right-0 top-full z-50 mt-1 min-w-[260px] rounded-xl border border-card-border bg-card-bg shadow-xl">
              <div className="border-b border-card-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted">
                Connected Accounts
              </div>
              {accounts.map((acct) => (
                <button
                  key={acct.broker}
                  onClick={() => { setActiveBroker(acct.broker); setDropdownOpen(false); }}
                  className={`flex w-full items-center justify-between px-3 py-2.5 hover:bg-sidebar-hover transition-colors ${
                    acct.broker === activeBroker ? "bg-sidebar-hover" : ""
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-green-400" />
                    <span className="text-sm font-medium capitalize text-foreground">
                      {acct.broker}
                    </span>
                    {acct.broker === activeBroker && (
                      <span className="rounded-full bg-accent/20 px-1.5 py-0.5 text-[10px] text-accent">
                        active
                      </span>
                    )}
                  </div>
                  <div className="text-right">
                    <div className="text-xs font-medium text-foreground">
                      {fmtBalance(acct.balance, acct.currency)}
                    </div>
                    <div className={`text-[10px] ${acct.unrealizedPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {acct.unrealizedPnl >= 0 ? "+" : ""}
                      {acct.unrealizedPnl.toFixed(2)} P&L
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* User menu */}
        {user && (
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted">{user.username}</span>
            <button
              onClick={logout}
              className="rounded-lg px-3 py-1.5 text-xs text-muted hover:bg-sidebar-hover hover:text-foreground transition-colors"
            >
              Logout
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
