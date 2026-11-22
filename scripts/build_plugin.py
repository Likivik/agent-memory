"""Build the self-contained Hermes plugin directory (P10 HP1).

Usage: uv run python scripts/build_plugin.py [--out ~/.hermes/plugins/mnemobun]

Copies the vendored `mnemobun` package payloads into hermes-plugin/lib/
and (with --out) installs plugin.yaml + __init__.py + lib/ to the target dir.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN_SRC = REPO / "hermes-plugin"
PACKAGES = [
    REPO / "packages" / "core" / "src" / "mnemobun",
    REPO / "packages" / "adapters" / "src" / "mnemobun",
    REPO / "packages" / "executor" / "src" / "mnemobun",
    REPO / "packages" / "mcp" / "src" / "mnemobun",
]


def build_lib(lib_dir: Path) -> int:
    if lib_dir.exists():
        shutil.rmtree(lib_dir)
    lib_dir.mkdir(parents=True)
    for src in PACKAGES:
        if not src.is_dir():
            raise SystemExit(f"missing package payload: {src}")
        shutil.copytree(src, lib_dir / "mnemobun", dirs_exist_ok=True)
    return sum(1 for _ in lib_dir.rglob("*.py"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default=None, help="install target (e.g. ~/.hermes/plugins/mnemobun)"
    )
    args = parser.parse_args()

    lib_dir = PLUGIN_SRC / "lib"
    n = build_lib(lib_dir)
    print(f"vendored lib: {n} python files -> {lib_dir}")

    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PLUGIN_SRC / "plugin.yaml", out / "plugin.yaml")
        shutil.copy2(PLUGIN_SRC / "__init__.py", out / "__init__.py")
        if (out / "lib").exists():
            shutil.rmtree(out / "lib")
        shutil.copytree(lib_dir, out / "lib")
        print(f"installed plugin -> {out}")


if __name__ == "__main__":
    main()
