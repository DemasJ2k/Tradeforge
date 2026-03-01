"""
Parse uploaded strategy files (.py, .json, .pine) to extract settings schemas.

Returns a dict with:
  - name: str
  - description: str
  - settings_schema: list[dict]  — [{key, label, type, default, min, max, step, options}]
  - settings_values: dict        — {key: default_value}
"""

import ast
import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_strategy_file(content: str, ext: str) -> dict:
    """Route to the appropriate parser based on file extension."""
    if ext == "py":
        return parse_python_strategy(content)
    elif ext == "json":
        return parse_json_strategy(content)
    elif ext in ("pine", "pinescript"):
        return parse_pinescript_strategy(content)
    else:
        raise ValueError(f"Unsupported file extension: .{ext}")


# ── Python Strategy Parser ─────────────────────────────────────────


def parse_python_strategy(content: str) -> dict:
    """
    Extract settings from a Python strategy file.

    Supports two patterns:
    1. Class-based: looks for SETTINGS dict or settings() classmethod
    2. Decorator-based: looks for @param decorators or PARAMS dict at module level
    3. Fallback: scans for assignments like `PARAM_NAME = value`
    """
    name = "Python Strategy"
    description = ""
    settings_schema: list[dict] = []
    settings_values: dict[str, Any] = {}

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        raise ValueError(f"Python syntax error: {e}")

    # Extract module docstring
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, (ast.Constant, ast.Str)):
        val = tree.body[0].value
        description = val.value if isinstance(val, ast.Constant) else val.s  # type: ignore

    # Look for class name
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            name = _camel_to_title(node.name)
            # Check class docstring
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Constant, ast.Str)):
                val = node.body[0].value
                description = val.value if isinstance(val, ast.Constant) else val.s  # type: ignore
            break

    # Pattern 1: Look for SETTINGS or PARAMS dict literal at class or module level
    found = _extract_dict_assignment(tree, {"SETTINGS", "PARAMS", "PARAMETERS", "CONFIG", "DEFAULTS"})
    if found:
        for key, val in found.items():
            schema_entry, value = _infer_schema_from_value(key, val)
            settings_schema.append(schema_entry)
            settings_values[key] = value
        return {"name": name, "description": description, "settings_schema": settings_schema, "settings_values": settings_values}

    # Pattern 2: Look for @param(...) decorators
    params_from_decorators = _extract_param_decorators(content)
    if params_from_decorators:
        for p in params_from_decorators:
            settings_schema.append(p)
            settings_values[p["key"]] = p.get("default", 0)
        return {"name": name, "description": description, "settings_schema": settings_schema, "settings_values": settings_values}

    # Pattern 3: Fallback — scan top-level or class-level ALL_CAPS assignments
    uppercase_assigns = _extract_uppercase_assignments(tree)
    if uppercase_assigns:
        for key, val in uppercase_assigns.items():
            schema_entry, value = _infer_schema_from_value(key, val)
            settings_schema.append(schema_entry)
            settings_values[key] = value

    return {"name": name, "description": description, "settings_schema": settings_schema, "settings_values": settings_values}


def _camel_to_title(name: str) -> str:
    """Convert CamelCase to Title Case."""
    s = re.sub(r"([A-Z])", r" \1", name).strip()
    return s.title() if s == s.upper() else s


def _extract_dict_assignment(tree: ast.Module, names: set[str]) -> dict[str, Any] | None:
    """Find a dict assignment like SETTINGS = {...} in the AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in names:
                if isinstance(node.value, ast.Dict):
                    return _eval_dict_literal(node.value)
    return None


def _eval_dict_literal(node: ast.Dict) -> dict[str, Any]:
    """Safely evaluate a dict literal from AST."""
    result = {}
    for k, v in zip(node.keys, node.values):
        if k is None:
            continue
        key = _eval_literal(k)
        val = _eval_literal(v)
        if isinstance(key, str):
            result[key] = val
    return result


def _eval_literal(node: ast.expr) -> Any:
    """Safely evaluate a literal value from AST."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Num):  # Python 3.7 compat
        return node.n  # type: ignore
    if isinstance(node, ast.Str):  # Python 3.7 compat
        return node.s  # type: ignore
    if isinstance(node, ast.List):
        return [_eval_literal(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return _eval_dict_literal(node)
    if isinstance(node, ast.NameConstant):  # Python 3.7 compat
        return node.value  # type: ignore
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        val = _eval_literal(node.operand)
        if isinstance(val, (int, float)):
            return -val
    if isinstance(node, ast.Name):
        if node.id in ("True", "true"):
            return True
        if node.id in ("False", "false"):
            return False
        if node.id in ("None", "null"):
            return None
    return None


def _extract_param_decorators(content: str) -> list[dict]:
    """Extract @param(...) decorator patterns from source code."""
    params = []
    pattern = re.compile(
        r'@param\s*\(\s*["\'](\w+)["\']\s*'
        r'(?:,\s*label\s*=\s*["\']([^"\']+)["\']\s*)?'
        r'(?:,\s*type\s*=\s*["\'](\w+)["\']\s*)?'
        r'(?:,\s*default\s*=\s*([^,)]+)\s*)?'
        r'(?:,\s*min\s*=\s*([^,)]+)\s*)?'
        r'(?:,\s*max\s*=\s*([^,)]+)\s*)?'
        r'(?:,\s*step\s*=\s*([^,)]+)\s*)?'
        r'\)',
        re.IGNORECASE,
    )
    for m in pattern.finditer(content):
        key = m.group(1)
        p: dict[str, Any] = {
            "key": key,
            "label": m.group(2) or _key_to_label(key),
            "type": m.group(3) or "float",
        }
        if m.group(4):
            p["default"] = _try_number(m.group(4).strip())
        if m.group(5):
            p["min"] = _try_number(m.group(5).strip())
        if m.group(6):
            p["max"] = _try_number(m.group(6).strip())
        if m.group(7):
            p["step"] = _try_number(m.group(7).strip())
        params.append(p)
    return params


def _extract_uppercase_assignments(tree: ast.Module) -> dict[str, Any]:
    """Extract ALL_CAPS = literal assignments from the top level and class bodies."""
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                val = _eval_literal(node.value)
                if val is not None and isinstance(val, (int, float, bool, str)):
                    result[target.id] = val
        elif isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                        val = _eval_literal(stmt.value)
                        if val is not None and isinstance(val, (int, float, bool, str)):
                            result[target.id] = val
    return result


# ── JSON Strategy Parser ───────────────────────────────────────────


def parse_json_strategy(content: str) -> dict:
    """
    Parse a JSON strategy file.

    Expected format:
    {
      "name": "...",
      "description": "...",
      "settings": {
        "param_name": value,
        ...
      },
      "settings_schema": [...],  // optional — if provided, used directly
      "logic": { ... }           // strategy logic (opaque to parser)
    }
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")

    name = data.get("name", "JSON Strategy")
    description = data.get("description", "")
    settings_schema: list[dict] = []
    settings_values: dict[str, Any] = {}

    # Use explicit schema if provided
    if "settings_schema" in data and isinstance(data["settings_schema"], list):
        settings_schema = data["settings_schema"]
        # Extract defaults
        for entry in settings_schema:
            if "key" in entry and "default" in entry:
                settings_values[entry["key"]] = entry["default"]
    elif "settings" in data and isinstance(data["settings"], dict):
        # Auto-generate schema from settings dict
        for key, val in data["settings"].items():
            schema_entry, value = _infer_schema_from_value(key, val)
            settings_schema.append(schema_entry)
            settings_values[key] = value
    elif "parameters" in data and isinstance(data["parameters"], dict):
        for key, val in data["parameters"].items():
            schema_entry, value = _infer_schema_from_value(key, val)
            settings_schema.append(schema_entry)
            settings_values[key] = value

    # Override settings_values with explicit values if provided
    if "settings" in data and isinstance(data["settings"], dict):
        for k, v in data["settings"].items():
            settings_values[k] = v

    return {"name": name, "description": description, "settings_schema": settings_schema, "settings_values": settings_values}


# ── Pine Script Strategy Parser ────────────────────────────────────


def parse_pinescript_strategy(content: str) -> dict:
    """
    Parse Pine Script input() declarations to extract parameters.

    Looks for patterns like:
      length = input(14, "RSI Length", minval=1)
      src = input.source(close, "Source")
      threshold = input.float(70.0, "Overbought", step=0.5)
      use_filter = input.bool(true, "Use Filter")
    """
    name = "Pine Script Strategy"
    description = ""

    # Extract strategy title
    title_match = re.search(r'strategy\s*\(\s*["\']([^"\']+)["\']', content)
    if title_match:
        name = title_match.group(1)

    settings_schema: list[dict] = []
    settings_values: dict[str, Any] = {}

    # Match input() / input.int() / input.float() / input.bool() / input.string()
    input_pattern = re.compile(
        r'(\w+)\s*=\s*input(?:\.(\w+))?\s*\('
        r'\s*([^,)]+)'                              # default value
        r'(?:\s*,\s*(?:title\s*=\s*)?["\']([^"\']+)["\'])?'  # title
        r'([^)]*)\)',                                # remaining args
        re.MULTILINE,
    )

    for m in input_pattern.finditer(content):
        var_name = m.group(1)
        input_type = m.group(2)  # int, float, bool, string, source, or None
        default_raw = m.group(3).strip()
        title = m.group(4) or _key_to_label(var_name)
        rest = m.group(5) or ""

        # Determine type
        if input_type in ("int",):
            ptype = "int"
        elif input_type in ("float",):
            ptype = "float"
        elif input_type in ("bool",):
            ptype = "bool"
        elif input_type in ("string",):
            ptype = "select"
        elif input_type in ("source",):
            continue  # skip source inputs
        else:
            # Infer from default value
            if default_raw in ("true", "false"):
                ptype = "bool"
            elif "." in default_raw:
                ptype = "float"
            else:
                ptype = "int"

        # Parse default
        default_val = _parse_pine_value(default_raw, ptype)

        entry: dict[str, Any] = {
            "key": var_name,
            "label": title,
            "type": ptype,
            "default": default_val,
        }

        # Extract minval, maxval, step from rest
        minval_match = re.search(r'minval\s*=\s*([^,)]+)', rest)
        maxval_match = re.search(r'maxval\s*=\s*([^,)]+)', rest)
        step_match = re.search(r'step\s*=\s*([^,)]+)', rest)
        options_match = re.search(r'options\s*=\s*\[([^\]]+)\]', rest)

        if minval_match:
            entry["min"] = _try_number(minval_match.group(1).strip())
        if maxval_match:
            entry["max"] = _try_number(maxval_match.group(1).strip())
        if step_match:
            entry["step"] = _try_number(step_match.group(1).strip())
        if options_match:
            opts = [o.strip().strip("\"'") for o in options_match.group(1).split(",")]
            entry["options"] = opts
            entry["type"] = "select"

        settings_schema.append(entry)
        settings_values[var_name] = default_val

    return {"name": name, "description": description, "settings_schema": settings_schema, "settings_values": settings_values}


def _parse_pine_value(raw: str, ptype: str) -> Any:
    """Parse a Pine Script literal value."""
    raw = raw.strip().strip("\"'")
    if ptype == "bool":
        return raw.lower() == "true"
    if ptype in ("int", "float"):
        return _try_number(raw)
    return raw


# ── Shared Helpers ──────────────────────────────────────────────────


def _key_to_label(key: str) -> str:
    """Convert snake_case or UPPER_CASE to Title Case label."""
    return key.replace("_", " ").title()


def _try_number(s: str) -> int | float | str:
    """Try to parse a string as int or float."""
    s = s.strip()
    try:
        v = int(s)
        return v
    except ValueError:
        pass
    try:
        v = float(s)
        return v
    except ValueError:
        pass
    return s


def _infer_schema_from_value(key: str, val: Any) -> tuple[dict, Any]:
    """Infer a schema entry from a key/value pair."""
    if isinstance(val, bool):
        return {"key": key, "label": _key_to_label(key), "type": "bool", "default": val}, val
    elif isinstance(val, int):
        return {
            "key": key,
            "label": _key_to_label(key),
            "type": "int",
            "default": val,
            "min": 0,
            "max": val * 5 if val > 0 else 100,
            "step": 1,
        }, val
    elif isinstance(val, float):
        return {
            "key": key,
            "label": _key_to_label(key),
            "type": "float",
            "default": val,
            "min": 0.0,
            "max": round(val * 5, 2) if val > 0 else 100.0,
        }, val
    elif isinstance(val, str):
        return {"key": key, "label": _key_to_label(key), "type": "string", "default": val}, val
    elif isinstance(val, list):
        return {"key": key, "label": _key_to_label(key), "type": "select", "default": val[0] if val else "", "options": val}, val[0] if val else ""
    elif isinstance(val, dict):
        # Treat dict values as explicit schema entries
        entry: dict[str, Any] = {"key": key, "label": val.get("label", _key_to_label(key))}
        entry["type"] = val.get("type", "float")
        entry["default"] = val.get("default", 0)
        if "min" in val:
            entry["min"] = val["min"]
        if "max" in val:
            entry["max"] = val["max"]
        if "step" in val:
            entry["step"] = val["step"]
        if "options" in val:
            entry["options"] = val["options"]
        return entry, val.get("default", 0)
    else:
        return {"key": key, "label": _key_to_label(key), "type": "string", "default": str(val)}, str(val)
