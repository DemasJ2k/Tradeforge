"""Strategy Settings Parser — Extract SETTINGS from Python strategy files.

Each Python strategy file may define a top-level `SETTINGS` list that describes
its configurable parameters for the UI, similar to TradingView's input() system.

Format:
    SETTINGS = [
        {
            "key": "atr_period",
            "label": "ATR Period",
            "type": "int",        # int | float | bool | select | text
            "default": 14,
            "min": 5,
            "max": 50,
            "step": 1,
            "group": "Risk Management",
            "description": "Number of bars for ATR calculation",
        },
        {
            "key": "bos_confirm",
            "label": "BoS Confirmation",
            "type": "select",
            "default": "close",
            "options": ["close", "wick"],
            "group": "Entry Rules",
        },
        ...
    ]
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def parse_settings_from_file(filepath: str | Path) -> list[dict] | None:
    """Parse SETTINGS list from a Python strategy file.

    Returns the parsed list of setting dicts, or None if no SETTINGS found.
    Uses AST parsing for safety — does NOT execute the file.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return None

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.warning("Failed to parse %s: %s", filepath.name, e)
        return None

    # Find top-level SETTINGS assignment
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SETTINGS":
                    try:
                        value = ast.literal_eval(node.value)
                        if isinstance(value, list):
                            return value
                    except (ValueError, TypeError):
                        pass
    return None


def sync_strategy_settings(db: Session) -> int:
    """Sync settings_schema from SETTINGS declarations in Python strategy files.

    For each Python strategy in the DB whose file contains a SETTINGS declaration,
    update the strategy's settings_schema column with the parsed schema.

    Returns the number of strategies updated.
    """
    from app.models.strategy import Strategy

    strategies = (
        db.query(Strategy)
        .filter(Strategy.strategy_type == "python")
        .filter(Strategy.deleted_at.is_(None))
        .all()
    )

    updated = 0
    for s in strategies:
        if not s.file_path:
            continue

        # Resolve file path
        fp = Path(s.file_path)
        if not fp.is_absolute():
            # Try relative to backend data/strategies
            base = Path(__file__).resolve().parent.parent.parent / "data" / "strategies"
            fp = base / fp.name

        settings = parse_settings_from_file(fp)
        if settings is not None:
            s.settings_schema = settings
            # Also ensure settings_values has defaults for any missing keys
            current_vals = s.settings_values or {}
            if isinstance(current_vals, str):
                import json
                try:
                    current_vals = json.loads(current_vals)
                except (ValueError, TypeError):
                    current_vals = {}

            defaults = {item["key"]: item["default"] for item in settings if "key" in item and "default" in item}
            merged = {**defaults, **current_vals}
            s.settings_values = merged
            updated += 1
            logger.info("Synced settings for strategy '%s': %d params", s.name, len(settings))

    if updated:
        db.commit()
    return updated
