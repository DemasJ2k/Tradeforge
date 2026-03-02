"""
Build script for the TradeForge Rust core extension.

Usage:
    python build_rust_core.py          # Build in release mode
    python build_rust_core.py --dev    # Build in debug mode (faster compile)
    python build_rust_core.py --check  # Just check if Rust toolchain is installed

Requires:
    - Rust toolchain (rustup.rs)
    - maturin:   pip install maturin
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent / "backend" / "app" / "services" / "backtest" / "v2" / "core"


def check_prerequisites() -> dict[str, bool]:
    """Check if required tools are installed."""
    checks = {}

    # Rust
    checks["rustc"] = shutil.which("rustc") is not None
    checks["cargo"] = shutil.which("cargo") is not None

    # Maturin
    try:
        subprocess.run(
            [sys.executable, "-m", "maturin", "--version"],
            capture_output=True, check=True,
        )
        checks["maturin"] = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        checks["maturin"] = False

    return checks


def install_maturin() -> bool:
    """Install maturin via pip."""
    print("Installing maturin...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "maturin"],
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def build(release: bool = True) -> bool:
    """Build the Rust extension with maturin."""
    cmd = [sys.executable, "-m", "maturin", "develop"]
    if release:
        cmd.append("--release")

    print(f"Building TradeForge Rust core ({'release' if release else 'debug'})...")
    print(f"  Directory: {CORE_DIR}")
    print(f"  Command:   {' '.join(cmd)}")
    print()

    try:
        result = subprocess.run(
            cmd,
            cwd=str(CORE_DIR),
            check=True,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed with exit code {e.returncode}")
        return False
    except FileNotFoundError as e:
        print(f"\nBuild tool not found: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Build TradeForge Rust core")
    parser.add_argument("--dev", action="store_true", help="Debug build (faster compile)")
    parser.add_argument("--check", action="store_true", help="Just check prerequisites")
    args = parser.parse_args()

    print("=" * 60)
    print("TradeForge Rust Core Builder")
    print("=" * 60)
    print()

    # Check prerequisites
    checks = check_prerequisites()

    print("Prerequisites:")
    for tool, ok in checks.items():
        status = "OK" if ok else "MISSING"
        print(f"  {tool:12s} [{status}]")
    print()

    if args.check:
        if all(checks.values()):
            print("All prerequisites met. Ready to build.")
        else:
            print("Missing prerequisites. See above.")
        return

    # Check Rust
    if not checks["rustc"] or not checks["cargo"]:
        print("ERROR: Rust toolchain not found.")
        print("Install from: https://rustup.rs/")
        print()
        print("The Python fallback engine will be used instead.")
        print("(No performance penalty for correctness — only speed.)")
        sys.exit(1)

    # Check / install maturin
    if not checks["maturin"]:
        if not install_maturin():
            print("ERROR: Could not install maturin.")
            sys.exit(1)

    # Check Cargo.toml exists
    if not (CORE_DIR / "Cargo.toml").exists():
        print(f"ERROR: Cargo.toml not found in {CORE_DIR}")
        sys.exit(1)

    # Build
    release = not args.dev
    ok = build(release=release)

    print()
    if ok:
        print("BUILD SUCCESSFUL")
        print()
        # Verify import
        try:
            import tradeforge_core  # type: ignore[import-not-found]
            print(f"Module loaded: {tradeforge_core.__file__}")
        except ImportError:
            print("WARNING: Module built but import failed.")
            print("This may happen if the Python environment differs.")
    else:
        print("BUILD FAILED")
        print()
        print("The Python fallback engine will be used automatically.")
        print("No action needed — backtest results are identical.")
        sys.exit(1)


if __name__ == "__main__":
    main()
