import { create } from "zustand";

interface SidebarState {
  open: boolean;
  mobileOpen: boolean;
  toggle: () => void;
  setOpen: (v: boolean) => void;
  toggleMobile: () => void;
  setMobileOpen: (v: boolean) => void;
}

export const useSidebar = create<SidebarState>((set) => ({
  open: true,
  mobileOpen: false,
  toggle: () => set((s) => ({ open: !s.open })),
  setOpen: (v) => set({ open: v }),
  toggleMobile: () => set((s) => ({ mobileOpen: !s.mobileOpen })),
  setMobileOpen: (v) => set({ mobileOpen: v }),
}));
