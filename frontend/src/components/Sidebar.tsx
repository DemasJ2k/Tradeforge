"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { name: "Dashboard", href: "/", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
  { name: "Data", href: "/data", icon: "M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" },
  { name: "Strategies", href: "/strategies", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" },
  { name: "Backtest", href: "/backtest", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { name: "Optimize", href: "/optimize", icon: "M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" },
  { name: "ML Lab", href: "/ml", icon: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" },
  { name: "Trading", href: "/trading", icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" },
  { name: "Knowledge", href: "/knowledge", icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" },
  { name: "Settings", href: "/settings", icon: "M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93s.844.083 1.168-.168l.672-.535a1.126 1.126 0 011.539.1l.773.773c.426.426.478 1.1.12 1.584l-.503.632a1.342 1.342 0 00-.168 1.168c.166.396.506.71.93.78l.893.149c.543.09.94.56.94 1.11v1.093c0 .55-.397 1.02-.94 1.11l-.893.149c-.424.07-.764.384-.93.78s-.083.844.168 1.168l.503.632c.358.484.306 1.158-.12 1.584l-.773.773a1.126 1.126 0 01-1.539.1l-.672-.535a1.342 1.342 0 00-1.168-.168c-.396.166-.71.506-.78.93l-.149.893c-.09.543-.56.94-1.11.94h-1.093c-.55 0-1.02-.397-1.11-.94l-.149-.893a1.342 1.342 0 00-.78-.93 1.342 1.342 0 00-1.168.168l-.672.535a1.126 1.126 0 01-1.539-.1l-.773-.773a1.126 1.126 0 01-.12-1.584l.503-.632c.251-.324.295-.772.168-1.168s-.506-.71-.93-.78l-.894-.149A1.126 1.126 0 013 13.547v-1.093c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.764-.384.93-.78s.083-.844-.168-1.168l-.503-.632a1.126 1.126 0 01.12-1.584l.773-.773a1.126 1.126 0 011.539-.1l.672.535c.324.251.772.295 1.168.168s.71-.506.78-.93l.149-.894zM15 12a3 3 0 11-6 0 3 3 0 016 0z" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-56 flex-col bg-sidebar-bg border-r border-card-border">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 px-4 border-b border-card-border">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-black font-bold text-sm">
          TF
        </div>
        <span className="text-lg font-semibold text-foreground">TradeForge</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 mb-0.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-sidebar-active text-accent"
                  : "text-muted hover:bg-sidebar-hover hover:text-foreground"
              }`}
            >
              <svg
                className="h-5 w-5 shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d={item.icon}
                />
              </svg>
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Bottom section */}
      <div className="border-t border-card-border p-3">
        <div className="flex items-center gap-2 px-2 text-xs text-muted">
          <div className="h-2 w-2 rounded-full bg-success" />
          <span>TradeForge v0.1.0</span>
        </div>
      </div>
    </aside>
  );
}
