"use client";

import { create } from "zustand";
import { api } from "@/lib/api";
import type { User, Token } from "@/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  mustChangePassword: boolean;
  totpRequired: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
  loadUser: () => Promise<void>;
  clearFlags: () => void;
  refreshUser: () => Promise<void>;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  loading: true,
  mustChangePassword: false,
  totpRequired: false,

  login: async (username, password) => {
    const resp = await api.post<Token>("/api/auth/login", {
      username,
      password,
    });
    localStorage.setItem("token", resp.access_token);
    const user = await api.get<User>("/api/auth/me");
    set({
      user,
      mustChangePassword: resp.must_change_password,
      totpRequired: resp.totp_required,
    });
  },

  register: async (username, password) => {
    await api.post<User>("/api/auth/register", { username, password });
    // Auto-login after register
    const resp = await api.post<Token>("/api/auth/login", {
      username,
      password,
    });
    localStorage.setItem("token", resp.access_token);
    const user = await api.get<User>("/api/auth/me");
    set({
      user,
      mustChangePassword: resp.must_change_password,
      totpRequired: resp.totp_required,
    });
  },

  logout: () => {
    localStorage.removeItem("token");
    set({ user: null, mustChangePassword: false, totpRequired: false });
  },

  loadUser: async () => {
    try {
      const token = localStorage.getItem("token");
      if (!token) {
        set({ loading: false });
        return;
      }
      const user = await api.get<User>("/api/auth/me");
      set({
        user,
        loading: false,
        mustChangePassword: user.must_change_password,
      });
    } catch {
      localStorage.removeItem("token");
      set({ user: null, loading: false });
    }
  },

  clearFlags: () => {
    set({ mustChangePassword: false, totpRequired: false });
  },

  refreshUser: async () => {
    try {
      const user = await api.get<User>("/api/auth/me");
      set({ user });
    } catch {
      // ignore
    }
  },
}));
