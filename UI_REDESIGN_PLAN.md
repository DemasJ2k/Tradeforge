# FlowrexAlgo UI/UX Redesign Plan

> Rebrand from TradeForge → **FlowrexAlgo**
> Created: 2026-03-01

---

## 1. Brand Identity

| Aspect          | Decision                                                                 |
|-----------------|--------------------------------------------------------------------------|
| **Name**        | TradeForge → **FlowrexAlgo**                                            |
| **Logo**        | Abstract flow/wave icon + "FlowrexAlgo" wordmark. Monogram **"FA"** for collapsed sidebar. |
| **Default accent** | **Teal/Cyan** (#06b6d4 family) — evokes flow, movement, freshness    |
| **Dark mode**   | Dark by default, light toggle available                                  |

All references to "TradeForge" / "TF" replaced across: metadata, sidebar logo, topbar, footer version text, auth screens, page titles, backend API responses.

---

## 2. Design System & Stack Changes

| Area              | Current                              | New                                              |
|-------------------|--------------------------------------|--------------------------------------------------|
| **Components**    | Raw Tailwind + hardcoded styles      | **shadcn/ui** (Radix-based, copy-paste)          |
| **Icons**         | Raw SVG paths (Heroicons-style)      | **Lucide React**                                 |
| **Font**          | Geist Sans + Geist Mono             | **Inter** (body) + **JetBrains Mono** (code/numbers) |
| **Charts**        | Recharts + Lightweight Charts        | Same libs but **theme-aware** (auto-adapt to user accent/palette) |
| **Notifications** | None                                 | **Sonner** toast library (shadcn's default)      |
| **Command palette** | None                               | **cmdk** (Ctrl+K fuzzy navigation)               |
| **Resizable panels** | None                              | **react-resizable-panels** (for Backtest, Dashboard) |

---

## 3. Theme & Colour Customisation

**Approach: Presets + Custom Builder**

### 3.1 Curated Theme Presets (8-10)

| Preset            | Background | Card BG  | Accent  | Mood                       |
|-------------------|------------|----------|---------|----------------------------|
| Midnight Teal (default) | #0f172a | #1e293b | #06b6d4 | Deep, professional, flow |
| Ocean Blue        | #0c1222    | #162032  | #3b82f6 | Classic fintech            |
| Emerald Trader    | #0a1628    | #132238  | #10b981 | Growth, money-green        |
| Sunset Gold       | #1a1410    | #2a2218  | #f59e0b | Warm, luxurious            |
| Neon Purple       | #0d0b1a    | #1a1630  | #8b5cf6 | Premium, algorithmic       |
| Classic Dark      | #0a0a0a    | #18181b  | #3b82f6 | Current look, refined      |
| Arctic Light      | #f8fafc    | #ffffff  | #0891b2 | Clean light mode           |
| Warm Stone        | #1c1917    | #292524  | #f97316 | Earthy, warm               |

### 3.2 Custom Builder

User can start from any preset, then tweak individual CSS variables via colour picker:

- Background, Card BG, Card Border
- Accent, Accent Hover
- Text primary, Text muted
- Success, Danger
- Sidebar BG

**Export/Import** themes as JSON for sharing.

Charts, buttons, badges all react to these variables automatically.

---

## 4. Layout & Navigation

**Keep: polished sidebar + topbar** (current structure, refined)

### 4.1 Sidebar Upgrades
- Lucide icons replace raw SVG paths
- "FA" monogram badge when collapsed, full "FlowrexAlgo" wordmark when expanded
- Active item gets a subtle left accent bar + highlighted bg
- Smooth collapse/expand animation
- Keyboard shortcut hints next to nav items (optional)

### 4.2 TopBar Upgrades
- Breadcrumbs showing current page context (e.g. "Strategies > My SMA Cross")
- User avatar + dropdown (profile, theme settings, logout)
- Broker balance stays, styled as a subtle badge
- Global search trigger (Ctrl+K icon)

### 4.3 Command Palette (Ctrl+K)
- Fuzzy search across: pages, strategies by name, data sources, recent backtests
- Quick actions: "New Strategy", "Run Backtest", "Open Settings"

---

## 5. Card & Panel Style

**Hybrid approach:**
- **Main data panels** (stats grids, trade tables, forms) → flat cards with subtle border, no shadow
- **Overlays, modals, command palette, toasts** → glassmorphism (backdrop-blur, semi-transparent bg, subtle glow border)
- **Hover states** → slight elevation lift on interactive cards (strategies list, backtest results)

---

## 6. Typography

- **Body:** Inter (clean, serious, TradingView/Bloomberg family)
- **Code/numbers:** JetBrains Mono (for trade prices, metrics, code snippets)
- **Base size:** 14px (comfortable density)

---

## 7. Animations

**Minimal / none:**
- No page transitions or fancy entry animations
- Instant content rendering
- Smooth hover states and focus rings (CSS transitions only, ~150ms)
- Sidebar collapse is the one exception: smooth width transition (already exists)

---

## 8. Implementation Phases

### Phase A — Global Shell (FIRST)
- [x] Install shadcn/ui + Lucide + Inter font + Sonner + cmdk
- [x] Rebuild Sidebar, TopBar, Layout with new components
- [x] Implement theme system (presets + custom builder in Settings)
- [x] Rebrand all "TradeForge" → "FlowrexAlgo"
- [x] Toast notification system
- [x] Command palette

### Phase B — Backtest Page
- [x] Split into resizable panels: form (left) | results (right)
- [x] Metrics grid using shadcn Card components
- [x] Equity chart + trade table in resizable split
- [x] Portfolio tab with proper data tables (shadcn DataTable)
- [x] Theme-aware chart colours
- [x] Bulk colour token migration (all pages)
- [x] All inline SVGs → Lucide React icons (all pages)

### Phase C — Strategy Editor
- [x] Redesign rule builder with shadcn Select, Input, Card
- [x] Better visual flow for entry/exit rules (connector lines, IF/AND/OR badges)
- [x] Indicator picker as a searchable combobox (Popover + Command)
- [x] Risk params in a collapsible accordion
- [x] Empty state with illustration when no strategy selected
- [x] shadcn Tabs for tab navigation (with icons + count badges)
- [x] Strategy summary as visual metric cards

### Phase D — Remaining Pages
- [x] Dashboard: KPI cards, positions table, P&L chart (resizable)
- [x] Data, Optimize, ML Lab, Trading, Knowledge: consistent card/table patterns
- [x] AgentPanel: Card wrappers, Dialog modals, Badge/Button/Label upgrades
- [x] Onboarding: empty-state illustrations with CTAs for each page

---

## 9. File Impact Summary

| Area               | Files Affected                                                   |
|--------------------|------------------------------------------------------------------|
| **Rebrand**        | `layout.tsx`, `Sidebar.tsx`, `TopBar.tsx`, `globals.css`, `package.json`, backend `main.py` title |
| **shadcn/ui setup** | New `components/ui/` folder (button, card, input, select, dialog, table, command, sonner, etc.) |
| **Theme system**   | `globals.css` (expanded vars), new `ThemeProvider`, Settings page theme section |
| **Sidebar**        | `Sidebar.tsx` (Lucide icons, new logo, accent bar)              |
| **TopBar**         | `TopBar.tsx` (breadcrumbs, avatar, Ctrl+K trigger)              |
| **Command palette** | New `CommandPalette.tsx` component                              |
| **Backtest**       | `backtest/page.tsx` (resizable panels, shadcn components)        |
| **Strategy editor** | `StrategyEditor.tsx` (shadcn form components)                   |
| **All pages**      | Migrate hardcoded Tailwind classes to shadcn/design-token patterns |

---

## 10. Design References

- **TradingView** (tradingview.com) — overall layout feel, comfortable density, clean dark mode
- **Linear** (linear.app) — command palette, sidebar polish, subtle hover states
- **Wealthsimple** (wealthsimple.com/trade) — teal accent, clean financial dashboard
- **Dub.co** (dub.co) — shadcn/ui in production
- **shadcn/ui Themes** (ui.shadcn.com/themes) — preview different colour schemes live
- **Cal.com** (cal.com) — shadcn/ui app, settings pages and forms reference
