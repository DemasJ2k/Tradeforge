"use client";

import { create } from "zustand";
import { api } from "@/lib/api";
import type { UserSettings } from "@/types";

interface SettingsState {
  settings: UserSettings | null;
  loaded: boolean;
  loadSettings: () => Promise<void>;
  updateSettings: (patch: Partial<UserSettings>) => void;
  applyToDOM: (s: UserSettings) => void;
}

function applySettingsToDOM(s: UserSettings) {
  const root = document.documentElement;

  // Theme: add/remove "dark" class
  if (s.theme === "dark") {
    root.classList.add("dark");
  } else if (s.theme === "light") {
    root.classList.remove("dark");
  } else {
    // "system" — follow OS preference
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (prefersDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }

  // Accent color
  if (s.accent_color) {
    root.setAttribute("data-accent", s.accent_color);
  }

  // Font size
  if (s.font_size) {
    root.setAttribute("data-fontsize", s.font_size);
  }
}

export const useSettings = create<SettingsState>((set, get) => ({
  settings: null,
  loaded: false,

  loadSettings: async () => {
    try {
      const token = localStorage.getItem("token");
      if (!token) {
        set({ loaded: true });
        return;
      }
      const s = await api.get<UserSettings>("/api/settings");
      set({ settings: s, loaded: true });
      applySettingsToDOM(s);
    } catch {
      set({ loaded: true });
    }
  },

  updateSettings: (patch) => {
    const current = get().settings;
    if (!current) return;
    const updated = { ...current, ...patch };
    set({ settings: updated });
    applySettingsToDOM(updated);
  },

  applyToDOM: (s) => applySettingsToDOM(s),
}));
