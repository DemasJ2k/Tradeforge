"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useSidebar } from "@/hooks/useSidebar";
import {
  LayoutDashboard,
  Database,
  FileCode2,
  BarChart3,
  SlidersHorizontal,
  Brain,
  TrendingUp,
  BookOpen,
  Settings,
  PanelLeftClose,
  PanelLeft,
  type LucideIcon,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface NavItem {
  name: string;
  href: string;
  icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Data", href: "/data", icon: Database },
  { name: "Strategies", href: "/strategies", icon: FileCode2 },
  { name: "Backtest", href: "/backtest", icon: BarChart3 },
  { name: "Optimize", href: "/optimize", icon: SlidersHorizontal },
  { name: "ML Lab", href: "/ml", icon: Brain },
  { name: "Trading", href: "/trading", icon: TrendingUp },
  { name: "Documents", href: "/knowledge", icon: BookOpen },
  { name: "Settings", href: "/settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { open, toggle } = useSidebar();

  return (
    <aside
      className={`relative flex h-screen flex-col bg-fa-sidebar-bg border-r border-fa-card-border transition-all duration-200 ${
        open ? "w-56" : "w-14"
      }`}
    >
      {/* Header: logo + toggle button */}
      <div className="flex h-14 items-center border-b border-fa-card-border px-2">
        {/* Toggle button — always visible */}
        <button
          onClick={toggle}
          title={open ? "Collapse sidebar (Ctrl+B)" : "Expand sidebar (Ctrl+B)"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-fa-sidebar-hover hover:text-foreground transition-colors"
        >
          {open ? <PanelLeftClose className="h-5 w-5" /> : <PanelLeft className="h-5 w-5" />}
        </button>

        {/* Logo + wordmark — only when expanded */}
        {open && (
          <div className="ml-2 flex items-center gap-2 overflow-hidden">
            <Image src="/logo.png" alt="FlowrexAlgo" width={32} height={32} className="shrink-0 rounded-lg" />
            <span className="text-base font-semibold text-foreground whitespace-nowrap tracking-tight">
              FlowrexAlgo
            </span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);

          const Icon = item.icon;

          const linkContent = (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-2 py-2.5 mb-0.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-fa-sidebar-active text-accent fa-active-bar"
                  : "text-muted-foreground hover:bg-fa-sidebar-hover hover:text-foreground"
              } ${!open ? "justify-center" : ""}`}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} />
              {open && <span className="whitespace-nowrap overflow-hidden">{item.name}</span>}
            </Link>
          );

          // Show tooltip when collapsed
          if (!open) {
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>{linkContent}</TooltipTrigger>
                <TooltipContent side="right" sideOffset={8}>
                  {item.name}
                </TooltipContent>
              </Tooltip>
            );
          }

          return linkContent;
        })}
      </nav>

      {/* Bottom section */}
      {open && (
        <div className="border-t border-fa-card-border p-3">
          <div className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
            <div className="h-2 w-2 rounded-full bg-fa-success" />
            <span>FlowrexAlgo v1.0</span>
          </div>
        </div>
      )}
    </aside>
  );
}
