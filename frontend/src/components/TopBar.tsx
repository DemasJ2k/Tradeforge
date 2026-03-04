"use client";

import { useEffect, useState, useRef } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useSidebar } from "@/hooks/useSidebar";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import {
  ChevronRight,
  ChevronDown,
  Search,
  LogOut,
  User,
  Menu,
} from "lucide-react";

const fmtBalance = (n: number, currency: string) => {
  const k = Math.abs(n) >= 1_000_000
    ? `${(n / 1_000_000).toFixed(2)}M`
    : Math.abs(n) >= 1_000
    ? `${(n / 1_000).toFixed(1)}k`
    : n.toFixed(2);
  return `${currency} ${k}`;
};

const ROUTE_LABELS: Record<string, string> = {
  "/": "Dashboard",
  "/data": "Data Sources",
  "/strategies": "Strategies",
  "/backtest": "Backtest",
  "/optimize": "Optimization",
  "/ml": "ML Lab",
  "/trading": "Trading",
  "/knowledge": "Documents",
  "/settings": "Settings",
};

export default function TopBar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { toggle, toggleMobile } = useSidebar();
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
    const interval = setInterval(refreshAccounts, 60_000);
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

  // Build breadcrumb from pathname
  const pageLabel = ROUTE_LABELS[pathname] || pathname.split("/").pop() || "Page";

  return (
    <header className="flex h-14 items-center justify-between border-b border-fa-card-border bg-fa-sidebar-bg px-2 sm:px-4">
      {/* Left: hamburger (mobile) + breadcrumb */}
      <div className="flex items-center gap-1.5 text-sm min-w-0">
        {/* Mobile hamburger */}
        <button
          onClick={toggleMobile}
          className="flex md:hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-fa-sidebar-hover hover:text-foreground transition-colors"
          title="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>
        <span className="hidden sm:inline text-muted-foreground">FlowrexAlgo</span>
        <ChevronRight className="hidden sm:inline h-3.5 w-3.5 text-muted-foreground/50" />
        <span className="font-medium text-foreground truncate">{pageLabel}</span>
      </div>

      {/* Right: search + broker + user */}
      <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">
        {/* Ctrl+K search trigger */}
        <button
          onClick={() => {
            const event = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true });
            document.dispatchEvent(event);
          }}
          className="flex items-center gap-2 rounded-lg border border-fa-card-border bg-fa-card-bg px-2 sm:px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Search...</span>
          <kbd className="hidden md:inline-flex h-5 items-center gap-0.5 rounded border border-fa-card-border bg-fa-sidebar-bg px-1.5 font-mono text-[10px] text-muted-foreground">
            Ctrl K
          </kbd>
        </button>

        {/* Broker account switcher */}
        <div className="relative hidden sm:block" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen((o) => !o)}
            className="flex items-center gap-2 rounded-lg bg-fa-card-bg px-3 py-1.5 text-xs hover:bg-fa-sidebar-hover transition-colors"
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
                <span className="text-muted-foreground">
                  {fmtBalance(activeAccount.balance, activeAccount.currency)}
                </span>
                {connectedCount > 1 && (
                  <span className="ml-1 rounded-full bg-accent/20 px-1.5 py-0.5 text-[10px] text-accent">
                    +{connectedCount - 1}
                  </span>
                )}
              </>
            ) : (
              <span className="text-muted-foreground">No broker connected</span>
            )}
            {connectedCount > 0 && (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            )}
          </button>

          {dropdownOpen && connectedCount > 0 && (
            <div className="absolute right-0 top-full z-50 mt-1 min-w-[260px] rounded-xl border border-fa-card-border bg-fa-card-bg shadow-xl">
              <div className="border-b border-fa-card-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Connected Accounts
              </div>
              {accounts.map((acct) => (
                <button
                  key={acct.broker}
                  onClick={() => { setActiveBroker(acct.broker); setDropdownOpen(false); }}
                  className={`flex w-full items-center justify-between px-3 py-2.5 hover:bg-fa-sidebar-hover transition-colors ${
                    acct.broker === activeBroker ? "bg-fa-sidebar-hover" : ""
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
          <div className="flex items-center gap-1 sm:gap-2">
            <div className="hidden sm:flex items-center gap-1.5 text-sm text-muted-foreground">
              <User className="h-4 w-4" />
              <span>{user.username}</span>
            </div>
            <button
              onClick={logout}
              title="Logout"
              className="flex items-center gap-1.5 rounded-lg px-2 sm:px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-fa-sidebar-hover hover:text-foreground transition-colors"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
