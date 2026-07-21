from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
from pathlib import Path


ENTRYPOINTS = {"bridge.py", "loom_cli.py", "loom_mcp.py"}
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", "tests"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage LOOM Python resources as sourceless bytecode.")
    parser.add_argument("--source", required=True, help="Source python directory.")
    parser.add_argument("--target", required=True, help="Output protected python directory.")
    return parser.parse_args()


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        destination = target / rel
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def compile_sources(target: Path) -> tuple[int, int]:
    compiled = 0
    loaders = 0
    for py_file in sorted(target.rglob("*.py")):
        py_compile.compile(str(py_file), cfile=str(py_file.with_suffix(".pyc")), doraise=True, optimize=1)
        compiled += 1

    for py_file in sorted(target.rglob("*.py")):
        if py_file.name in ENTRYPOINTS:
            write_loader(py_file)
            loaders += 1
        elif py_file.name == "__init__.py":
            py_file.write_text('"""LOOM protected package marker."""\n', encoding="utf-8")
            loaders += 1
        else:
            py_file.unlink()
    return compiled, loaders


def write_loader(path: Path) -> None:
    pyc_name = path.with_suffix(".pyc").name
    path.write_text(
        "from __future__ import annotations\n"
        "import os\n"
        "from importlib.machinery import SourcelessFileLoader\n"
        f"_protected_path = os.path.join(os.path.dirname(__file__), {pyc_name!r})\n"
        "_protected_loader = SourcelessFileLoader(__name__, _protected_path)\n"
        "_protected_code = _protected_loader.get_code(__name__)\n"
        "if _protected_code is None:\n"
        "    raise ImportError(f'Unable to load protected module: {_protected_path}')\n"
        "exec(_protected_code, globals(), globals())\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    if not source.is_dir():
        raise SystemExit(f"source is not a directory: {source}")
    copy_tree(source, target)
    compiled, loaders = compile_sources(target)
    manifest = {
        "schema": "loom.protected_python.v1",
        "source": str(source),
        "target": str(target),
        "compiledFiles": compiled,
        "sourceLoaders": loaders,
    }
    (target / "protected-python-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
