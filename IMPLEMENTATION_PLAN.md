# TradeForge — Strategy System Overhaul: Implementation Plan

## Problem Summary

### Bug: Backtest Sync (SL/TP changes ignored for MSS & Gold BT)

**Root Cause Identified:**

MSS and Gold BT strategies store their config in a dedicated sub-object inside `filters`:
- MSS: `strategy.filters.mss_config` → `{ swing_lb, tp1_pct, tp2_pct, sl_pct, use_pullback, pb_pct, confirm }`
- Gold BT: `strategy.filters.gold_bt_config` → `{ box_height, stop_line_buffer, sl_fixed_usd, ... }`

The `StrategyEditor` Risk tab edits `strategy.risk_params` (e.g., `stop_loss_value`, `take_profit_value`), but the dedicated MSS/Gold BT backtester functions (`backtest_mss()`, `backtest_gold_bt()`) read ONLY from `mss_config`/`gold_bt_config` and completely ignore `risk_params`.

**Data Flow:**
```
User edits SL in Risk tab
  → writes to risk_params.stop_loss_value
  → backtest API re-fetches strategy from DB ✓
  → detects mss_config in filters → calls backtest_mss(mss_config=...)
  → backtest_mss reads sl_pct from mss_config → UNCHANGED
  → identical results
```

**Same bug affects optimization:** `extractOptimizableParams()` only extracts from `risk_params` and `indicators[].params`, missing all MSS/Gold BT specific params. The optimizer's "Apply Best Params" writes to `risk_params` via `_set_nested`, which MSS/Gold BT backtests ignore.

### Feature: Strategy File Import System

User wants to upload Python (.py), JSON, and Pine Script files as strategies, with TradingView-style settings modals and optimization integration.

---

## Implementation Plan

### Part 1: Fix Backtest Sync Bug

**Approach:** Add MSS/Gold BT-aware editing to the StrategyEditor, so changes write to the CORRECT config location (`filters.mss_config.*` / `filters.gold_bt_config.*`).

#### 1A. StrategyEditor — Detect & expose MSS/Gold BT params

**File:** `frontend/src/components/StrategyEditor.tsx`

1. Detect strategy type from `filters`:
   ```ts
   const strategyType = filters.mss_config ? 'mss'
     : filters.gold_bt_config ? 'gold_bt' : 'generic';
   ```

2. For MSS strategies, in the Risk tab, REPLACE the standard SL/TP fields with MSS-specific fields that read/write to `filters.mss_config.*`:
   - **SL % (of ADR10)** → `filters.mss_config.sl_pct` (currently shows as stop_loss_value which is ignored)
   - **TP1 % (of ADR10)** → `filters.mss_config.tp1_pct`
   - **TP2 % (of ADR10)** → `filters.mss_config.tp2_pct`
   - **Swing Lookback** → `filters.mss_config.swing_lb`
   - **Use Pullback Entry** → `filters.mss_config.use_pullback` (checkbox)
   - **Pullback Ratio** → `filters.mss_config.pb_pct`
   - **Confirmation** → `filters.mss_config.confirm` (dropdown: "close" | "wick")

3. For Gold BT strategies, similar treatment:
   - **Box Height** → `filters.gold_bt_config.box_height`
   - **SL Fixed USD** → `filters.gold_bt_config.sl_fixed_usd`
   - **Stop Line Buffer** → `filters.gold_bt_config.stop_line_buffer`
   - (other gold_bt_config fields)

4. For generic strategies, keep the existing Risk tab unchanged (it works correctly).

5. The `handleSave` already sends `filters` which includes the nested config objects. No change needed there — we just need the UI to modify the right fields.

**Implementation detail:**
```tsx
// In the Risk tab rendering:
{strategyType === 'mss' && (
  <MSSRiskParams
    config={filters.mss_config}
    onChange={(key, val) => setFilters({
      ...filters,
      mss_config: { ...filters.mss_config, [key]: val }
    })}
  />
)}
{strategyType === 'gold_bt' && (
  <GoldBTRiskParams
    config={filters.gold_bt_config}
    onChange={(key, val) => setFilters({
      ...filters,
      gold_bt_config: { ...filters.gold_bt_config, [key]: val }
    })}
  />
)}
{strategyType === 'generic' && (
  // existing Risk tab content (unchanged)
)}
```

#### 1B. Optimization — Extract MSS/Gold BT params

**File:** `frontend/src/app/optimize/page.tsx`

Update `extractOptimizableParams()` to also extract from MSS/Gold BT configs:
```ts
// After existing indicator/risk_params extraction:
const filters = strategy.filters || {};
const mssConfig = filters.mss_config;
if (mssConfig) {
  params.push(
    { param_path: "filters.mss_config.sl_pct", param_type: "float",
      min_val: 5, max_val: 50, label: "MSS SL % (of ADR)" },
    { param_path: "filters.mss_config.tp1_pct", param_type: "float",
      min_val: 5, max_val: 40, label: "MSS TP1 % (of ADR)" },
    { param_path: "filters.mss_config.tp2_pct", param_type: "float",
      min_val: 10, max_val: 60, label: "MSS TP2 % (of ADR)" },
    { param_path: "filters.mss_config.swing_lb", param_type: "int",
      min_val: 10, max_val: 100, step: 2, label: "MSS Swing Lookback" },
    { param_path: "filters.mss_config.pb_pct", param_type: "float",
      min_val: 0.1, max_val: 0.9, label: "MSS Pullback Ratio" },
  );
}
const goldConfig = filters.gold_bt_config;
if (goldConfig) {
  // Similar extraction for gold_bt params
}
```

The optimization engine already uses `_set_nested()` with dot notation paths, so `filters.mss_config.sl_pct` will correctly update the nested value. The backtest engine already reads the full strategy from DB including filters, so optimized params will be picked up.

#### 1C. No backend changes needed for sync fix

The backend correctly:
- Saves all fields including `filters` with nested configs (strategy.py PUT endpoint)
- Re-fetches strategy from DB on each backtest run (backtest.py lines 117-126)
- Reads MSS params from `filters.mss_config` (strategy_backtester.py)

The bug is purely a frontend issue — the editor UI writes to the wrong location.

---

### Part 2: Strategy File Import System

#### 2A. New DB fields for file-based strategies

**File:** `backend/app/models/strategy.py`

Add columns:
```python
strategy_type = Column(String(20), default="builder")  # "builder" | "python" | "json" | "pinescript"
file_path = Column(String(500), nullable=True)  # path to uploaded strategy file on disk
file_hash = Column(String(64), nullable=True)  # SHA-256 for change detection
settings_schema = Column(JSON, default=list)  # auto-detected params: [{name, type, default, min, max, label, group}]
settings_values = Column(JSON, default=dict)  # user-overridden values: {param_name: value}
```

#### 2B. Strategy file upload endpoint

**File:** `backend/app/api/strategy.py`

New endpoint: `POST /api/strategies/upload-file`
```python
@router.post("/upload-file", status_code=201)
async def upload_strategy_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate extension: .py, .json, .pine, .pinescript
    # Save file to UPLOAD_DIR/strategies/{user_id}/{filename}
    # Parse file to detect strategy type and extract settings schema
    # Create Strategy DB record with strategy_type, file_path, settings_schema
    # Return strategy JSON with parsed settings
```

#### 2C. File parsers — extract settings schema

**New file:** `backend/app/services/strategy/file_parser.py`

```python
def parse_strategy_file(file_content: str, filename: str, file_type: str) -> dict:
    """Parse a strategy file and extract:
    - name, description
    - settings_schema: list of detected parameters with types, defaults, ranges
    - strategy_type: 'python' | 'json' | 'pinescript'
    """
```

**Python parser** — supports two styles:

Style 1: Class-based
```python
class MyStrategy(Strategy):
    # Settings
    fast_ma = Parameter(20, min=5, max=100, label="Fast MA Period")
    slow_ma = Parameter(50, min=10, max=300, label="Slow MA Period")
    sl_pips = Parameter(30, min=5, max=200, label="Stop Loss Pips")

    def on_bar(self, bar):
        ...
```

Style 2: Decorator-based
```python
@tf.param("fast_ma", default=20, min=5, max=100, label="Fast MA Period")
@tf.param("slow_ma", default=50, min=10, max=300, label="Slow MA Period")
def strategy(bars, params):
    ...
```

**JSON parser** — reads structured strategy definition:
```json
{
  "name": "My Strategy",
  "description": "...",
  "settings": [
    {"name": "period", "type": "int", "default": 20, "min": 5, "max": 100},
    {"name": "sl_multiplier", "type": "float", "default": 1.5}
  ],
  "indicators": [...],
  "entry_rules": [...],
  "exit_rules": [...],
  "risk_params": {...}
}
```

**Pine Script parser** — uses regex to extract `input()` calls:
```pinescript
fast = input(20, "Fast MA", minval=5, maxval=100)
slow = input(50, "Slow MA", minval=10)
```
→ Extracts: `{ name: "fast", type: "int", default: 20, min: 5, max: 100, label: "Fast MA" }`

Also leverages the existing AI parser (`ai_parser.py`) to convert Pine Script logic into TradeForge format via LLM when the user wants to convert to native format.

#### 2D. Python strategy execution engine

**New file:** `backend/app/services/strategy/python_runner.py`

For Python strategies, provide two execution modes:

**Mode 1: Direct execution** (sandboxed)
```python
def run_python_strategy(
    file_path: str,
    bars: list[Bar],
    settings: dict,
    initial_balance: float,
    ...
) -> BacktestResult:
    """Execute Python strategy file in a sandboxed environment."""
    # Load strategy module via importlib
    # Inject settings values as params
    # Call strategy's backtest entry point
    # Collect trades and build BacktestResult
```

**Mode 2: Conversion to internal engine**
- Parse Python file → extract indicators, entry/exit logic
- Convert to native TradeForge format (indicators, entry_rules, exit_rules, risk_params)
- Use existing BacktestEngine for execution

User chooses which mode when running backtest/optimization.

#### 2E. JSON strategy handler

**New file:** `backend/app/services/strategy/json_handler.py`

JSON strategies map directly to TradeForge's internal format:
- `indicators` → `strategy.indicators`
- `entry_rules` → `strategy.entry_rules`
- `exit_rules` → `strategy.exit_rules`
- `risk_params` → `strategy.risk_params`
- `settings` → `strategy.settings_schema` + user values in `settings_values`

On backtest, merge `settings_values` overrides into the strategy config before running.

#### 2F. Backtest API — handle file-based strategies

**File:** `backend/app/api/backtest.py`

Update the backtest run endpoint to handle file-based strategies:
```python
if strategy.strategy_type == "python":
    from app.services.strategy.python_runner import run_python_strategy
    result = run_python_strategy(
        file_path=strategy.file_path,
        bars=bars,
        settings=strategy.settings_values or {},
        initial_balance=payload.initial_balance,
        ...
    )
elif strategy.strategy_type == "json":
    # Merge settings_values into config, then run BacktestEngine
elif strategy.strategy_type == "pinescript":
    # Use AI-converted version or Pine interpreter
elif mss_config:
    # existing MSS path
elif gold_bt_config:
    # existing Gold BT path
else:
    # existing generic BacktestEngine path
```

---

### Part 3: TradingView-Style Settings Modal

#### 3A. Settings modal component

**New file:** `frontend/src/components/StrategySettingsModal.tsx`

A modal dialog (centered popup) that shows editable strategy parameters:

```
┌─────────────────────────────────────────┐
│  ⚙ Strategy Settings              [✕]  │
├─────────────────────────────────────────┤
│  ┌─────────┐ ┌───────┐                 │
│  │ Inputs  │ │ Style │                 │
│  └─────────┘ └───────┘                 │
│                                         │
│  ─── Trend Detection ──────────         │
│  Fast MA Period     [  20  ] ↕          │
│  Slow MA Period     [  50  ] ↕          │
│                                         │
│  ─── Risk Management ──────────         │
│  Stop Loss Pips     [  30  ] ↕          │
│  Take Profit R:R    [ 2.0  ] ↕          │
│                                         │
│  ─── Filters ──────────────────         │
│  Min ADX            [  20  ] ↕          │
│  Session Start      [08:00 ]            │
│                                         │
│  [Reset Defaults]          [OK] [Cancel]│
└─────────────────────────────────────────┘
```

Features:
- **Two tabs**: Inputs (parameters) and Style (visual settings for chart display)
- **Grouped parameters**: settings grouped by `group` field from schema
- **Input types**: number (with spinner), text, boolean (checkbox), select (dropdown)
- **Range validation**: respects min/max from schema
- **Reset defaults**: restores all params to their default values from schema
- **Real-time preview**: for applicable settings (e.g., MA period → chart updates)
- **OK saves to DB**, Cancel discards

#### 3B. Settings button on strategy cards

**File:** `frontend/src/app/strategies/page.tsx`

Add a gear icon (⚙) button on each strategy card that opens the settings modal:
```tsx
<button onClick={() => openSettings(s)}>
  ⚙
</button>
```

For builder-based strategies, this opens the existing StrategyEditor.
For file-based strategies, this opens the new SettingsModal.

#### 3C. Settings on backtest page

**File:** `frontend/src/app/backtest/page.tsx`

When a strategy is selected in the backtest config, show a "⚙ Settings" button next to the strategy dropdown that opens the settings modal. This lets users tweak parameters before running a backtest without navigating away.

#### 3D. Backend — settings update endpoint

**File:** `backend/app/api/strategy.py`

New endpoint: `PUT /api/strategies/{id}/settings`
```python
@router.put("/{strategy_id}/settings")
def update_strategy_settings(
    strategy_id: int,
    payload: dict,  # {param_name: value, ...}
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update user-configured settings values for a strategy."""
    # Validate values against settings_schema (type, min, max)
    # Save to strategy.settings_values
```

---

### Part 4: Optimization Integration for File-Based Strategies

#### 4A. Extract optimizable params from file strategies

**File:** `frontend/src/app/optimize/page.tsx`

Update `extractOptimizableParams()` to handle file-based strategies:
```ts
if (strategy.settings_schema?.length) {
  // File-based strategy: extract from settings_schema
  for (const param of strategy.settings_schema) {
    if (param.type === 'int' || param.type === 'float') {
      params.push({
        param_path: `settings_values.${param.name}`,
        param_type: param.type,
        min_val: param.min ?? Math.round(param.default * 0.3),
        max_val: param.max ?? Math.round(param.default * 3),
        step: param.type === 'int' ? (param.step ?? 1) : undefined,
        label: param.label || param.name,
      });
    }
  }
}
```

#### 4B. Backend optimizer — handle settings_values

**File:** `backend/app/services/optimize/engine.py`

The optimizer already uses `_set_nested(config, path, value)`. For file-based strategies, the param paths will be `settings_values.period`, `settings_values.sl_pips`, etc. The `_evaluate()` method needs to:

1. If `strategy_type == "python"`: apply settings_values to Python strategy, run via `python_runner`
2. If `strategy_type == "json"`: merge settings_values into strategy config, run via BacktestEngine
3. Otherwise: existing behavior

#### 4C. Optimization apply — file strategies

**File:** `backend/app/api/optimization.py`

The existing `apply_best_params` endpoint uses `_set_nested` to write optimized values. For file-based strategies with `settings_values.*` paths, this naturally writes to the `settings_values` column on the strategy. No special handling needed.

---

### Part 5: Frontend — File Upload UI

#### 5A. Upload modal on strategies page

**File:** `frontend/src/app/strategies/page.tsx`

Add a "Upload File" button alongside "AI Import" and "New Strategy":

```
[Upload File]  [AI Import]  [+ New Strategy]
```

The upload modal:
```
┌─────────────────────────────────────────┐
│  📂 Upload Strategy File          [✕]  │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  Drag & drop a strategy file   │    │
│  │  .py, .json, .pine             │    │
│  │  or click to browse            │    │
│  └─────────────────────────────────┘    │
│                                         │
│  Detected: Python Strategy              │
│  Name: "VWAP Breakout Scalper"          │
│  Parameters found: 8                    │
│                                         │
│  ☐ Convert to native format             │
│    (allows editing in Strategy Builder) │
│                                         │
│              [Cancel]  [Import Strategy] │
└─────────────────────────────────────────┘
```

After import, the strategy appears in the list with a file-type icon (🐍 Python, 📋 JSON, 🌲 Pine Script) and a gear icon for settings.

#### 5B. Strategy cards — file type indicators

**File:** `frontend/src/app/strategies/page.tsx`

Update strategy cards to show:
- File type icon (🐍 / 📋 / 🌲) for file-based strategies
- "⚙ Settings" button that opens SettingsModal (instead of full editor)
- "Edit" button still available for builder strategies
- "Convert to Builder" option for file strategies (uses AI to convert)

#### 5C. TypeScript types

**File:** `frontend/src/types/index.ts`

Add to Strategy interface:
```ts
interface Strategy {
  // existing fields...
  strategy_type?: 'builder' | 'python' | 'json' | 'pinescript';
  file_path?: string;
  settings_schema?: SettingsParam[];
  settings_values?: Record<string, unknown>;
}

interface SettingsParam {
  name: string;
  type: 'int' | 'float' | 'bool' | 'string' | 'select';
  default: unknown;
  min?: number;
  max?: number;
  step?: number;
  label?: string;
  group?: string;
  options?: string[];  // for select type
}
```

---

## Implementation Order

### Phase A: Backtest Sync Fix (Critical Bug)
1. **StrategyEditor.tsx** — Add MSS/Gold BT param editing in Risk tab
2. **optimize/page.tsx** — Add MSS/Gold BT param extraction
3. **Test** — Edit MSS SL → run backtest → verify results change

### Phase B: File Import Foundation
4. **strategy.py model** — Add new columns (strategy_type, file_path, settings_schema, settings_values)
5. **file_parser.py** — Python, JSON, Pine Script parsers
6. **strategy.py API** — Upload endpoint + settings update endpoint
7. **strategy.py API** — Update `_to_response()` to include new fields

### Phase C: Settings Modal
8. **StrategySettingsModal.tsx** — New component
9. **strategies/page.tsx** — Upload button + settings gear + file type icons
10. **backtest/page.tsx** — Settings button next to strategy dropdown

### Phase D: File Strategy Execution
11. **python_runner.py** — Python strategy sandboxed execution
12. **json_handler.py** — JSON strategy handler
13. **backtest.py API** — Route to correct runner based on strategy_type

### Phase E: Optimization Integration
14. **optimize/page.tsx** — Extract params from settings_schema
15. **optimize engine** — Handle settings_values in evaluation loop
16. **Test** — Full flow: upload Python file → settings → backtest → optimize → apply

---

## Files Modified (Summary)

### Frontend
| File | Change |
|------|--------|
| `components/StrategyEditor.tsx` | Add MSS/Gold BT risk param editing |
| `components/StrategySettingsModal.tsx` | **NEW** — TradingView-style settings popup |
| `app/strategies/page.tsx` | Upload button, file type icons, settings gear |
| `app/backtest/page.tsx` | Settings button next to strategy dropdown |
| `app/optimize/page.tsx` | Extract MSS/Gold BT/file params for optimization |
| `types/index.ts` | Add strategy_type, settings_schema, settings_values |

### Backend
| File | Change |
|------|--------|
| `models/strategy.py` | Add strategy_type, file_path, settings_schema, settings_values columns |
| `api/strategy.py` | Upload endpoint, settings update endpoint, _to_response update |
| `api/backtest.py` | Route to correct runner by strategy_type |
| `services/strategy/file_parser.py` | **NEW** — Python/JSON/Pine parsers |
| `services/strategy/python_runner.py` | **NEW** — Python strategy execution |
| `services/strategy/json_handler.py` | **NEW** — JSON strategy handler |

---

## Risk & Notes

- **Python execution sandboxing**: Running user-uploaded Python code is a security concern. For local deployment (current target), this is acceptable. For production, consider running in a subprocess with restricted imports and resource limits.
- **Pine Script**: Full Pine Script interpretation is complex. The approach is: (1) extract `input()` params for settings, (2) use AI parser to convert logic to native format, (3) optionally add a Pine interpreter later.
- **Migration**: New columns on Strategy model require a DB migration or `create_all()` update. SQLite will add them as nullable.
- **Backward compatibility**: Existing builder strategies continue to work unchanged (`strategy_type = "builder"` by default, no file_path or settings_schema).
