"use client";

import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <h1 className="text-6xl font-bold text-accent mb-4">404</h1>
      <p className="text-lg text-muted-foreground mb-6">Page not found</p>
      <Link
        href="/trading"
        className="px-4 py-2 rounded-lg bg-accent text-white hover:bg-accent/80 transition-colors"
      >
        Back to Trading
      </Link>
    </div>
  );
}
