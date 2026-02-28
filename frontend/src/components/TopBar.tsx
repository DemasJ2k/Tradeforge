"use client";

import { useEffect } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useSidebar } from "@/hooks/useSidebar";

export default function TopBar() {
  const { user, logout } = useAuth();
  const { toggle } = useSidebar();

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

  return (
    <header className="flex h-14 items-center justify-between border-b border-card-border bg-sidebar-bg px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-medium text-foreground">Dashboard</h1>
      </div>

      <div className="flex items-center gap-4">
        {/* Connection status */}
        <div className="flex items-center gap-2 rounded-lg bg-card-bg px-3 py-1.5 text-xs">
          <div className="h-2 w-2 rounded-full bg-muted" />
          <span className="text-muted">No broker connected</span>
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
