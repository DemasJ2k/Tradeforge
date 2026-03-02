"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
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
  Sun,
  Moon,
  Monitor,
  Palette,
} from "lucide-react";
import { useSettings } from "@/hooks/useSettings";

const PAGES = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard, keywords: ["home", "overview"] },
  { name: "Data Sources", href: "/data", icon: Database, keywords: ["csv", "upload", "import"] },
  { name: "Strategies", href: "/strategies", icon: FileCode2, keywords: ["rules", "conditions", "algo"] },
  { name: "Backtest", href: "/backtest", icon: BarChart3, keywords: ["simulate", "results", "equity"] },
  { name: "Optimization", href: "/optimize", icon: SlidersHorizontal, keywords: ["grid", "walk-forward", "params"] },
  { name: "ML Lab", href: "/ml", icon: Brain, keywords: ["machine learning", "model", "train", "predict"] },
  { name: "Trading", href: "/trading", icon: TrendingUp, keywords: ["live", "positions", "broker", "orders"] },
  { name: "Documents", href: "/knowledge", icon: BookOpen, keywords: ["docs", "guide", "help", "rag", "embeddings"] },
  { name: "Settings", href: "/settings", icon: Settings, keywords: ["preferences", "theme", "api", "config"] },
];

const THEME_PRESETS = [
  { name: "Midnight Teal", value: "preset:midnight-teal" },
  { name: "Ocean Blue", value: "preset:ocean-blue" },
  { name: "Emerald Trader", value: "preset:emerald-trader" },
  { name: "Sunset Gold", value: "preset:sunset-gold" },
  { name: "Neon Purple", value: "preset:neon-purple" },
  { name: "Classic Dark", value: "preset:classic-dark" },
  { name: "Warm Stone", value: "preset:warm-stone" },
  { name: "Arctic Light", value: "preset:arctic-light" },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { updateSettings } = useSettings();

  // Ctrl+K / Cmd+K to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const runAction = useCallback(
    (fn: () => void) => {
      setOpen(false);
      fn();
    },
    []
  );

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search pages, actions, themes..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        {/* Pages */}
        <CommandGroup heading="Pages">
          {PAGES.map((page) => {
            const Icon = page.icon;
            return (
              <CommandItem
                key={page.href}
                value={`${page.name} ${page.keywords.join(" ")}`}
                onSelect={() => runAction(() => router.push(page.href))}
              >
                <Icon className="mr-2 h-4 w-4 shrink-0" />
                <span>{page.name}</span>
              </CommandItem>
            );
          })}
        </CommandGroup>

        <CommandSeparator />

        {/* Theme switcher */}
        <CommandGroup heading="Appearance">
          <CommandItem
            value="light mode"
            onSelect={() =>
              runAction(() => {
                document.documentElement.classList.remove("dark");
                updateSettings({ theme: "light" });
              })
            }
          >
            <Sun className="mr-2 h-4 w-4" />
            <span>Light Mode</span>
          </CommandItem>
          <CommandItem
            value="dark mode"
            onSelect={() =>
              runAction(() => {
                document.documentElement.classList.add("dark");
                updateSettings({ theme: "dark" });
              })
            }
          >
            <Moon className="mr-2 h-4 w-4" />
            <span>Dark Mode</span>
          </CommandItem>
          <CommandItem
            value="system theme"
            onSelect={() => runAction(() => updateSettings({ theme: "system" }))}
          >
            <Monitor className="mr-2 h-4 w-4" />
            <span>System Theme</span>
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />

        {/* Theme presets */}
        <CommandGroup heading="Theme Presets">
          {THEME_PRESETS.map((preset) => (
            <CommandItem
              key={preset.value}
              value={`theme ${preset.name}`}
              onSelect={() =>
                runAction(() => updateSettings({ accent_color: preset.value }))
              }
            >
              <Palette className="mr-2 h-4 w-4" />
              <span>{preset.name}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
