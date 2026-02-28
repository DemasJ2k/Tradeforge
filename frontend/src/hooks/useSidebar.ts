import { create } from "zustand";

interface SidebarState {
  open: boolean;
  toggle: () => void;
  setOpen: (v: boolean) => void;
}

export const useSidebar = create<SidebarState>((set) => ({
  open: true,
  toggle: () => set((s) => ({ open: !s.open })),
  setOpen: (v) => set({ open: v }),
}));
