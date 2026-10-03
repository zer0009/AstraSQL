"""Static checks that layers respect the architecture import directions."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"


def _iter_py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _module_name(path: Path) -> str:
    rel = path.relative_to(BACKEND_SRC).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["src", *parts])


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            # Relative imports inside a package stay within that package.
            if node.level and node.level > 0:
                continue
            names.add(node.module)
    return names


def _imports_under(imports: set[str], prefix: str) -> list[str]:
    return sorted(
        name
        for name in imports
        if name == prefix or name.startswith(prefix + ".")
    )


@pytest.mark.parametrize("path", _iter_py_files(BACKEND_SRC / "api"))
def test_api_does_not_import_agent_nodes(path: Path) -> None:
    offenders = _imports_under(_imported_modules(path), "src.agent.nodes")
    assert not offenders, f"{_module_name(path)} imports agent nodes: {offenders}"


@pytest.mark.parametrize("path", _iter_py_files(BACKEND_SRC / "agent"))
def test_agent_does_not_import_api(path: Path) -> None:
    offenders = _imports_under(_imported_modules(path), "src.api")
    assert not offenders, f"{_module_name(path)} imports api: {offenders}"


@pytest.mark.parametrize(
    "path",
    [
        p
        for p in _iter_py_files(BACKEND_SRC)
        if "eval" not in p.parts and "scripts" not in p.parts
    ],
)
def test_runtime_does_not_import_eval(path: Path) -> None:
    """Production packages must not depend on the offline eval harness."""
    if path.parts[-2:] == ("eval",) or "eval" in path.parts:
        return
    offenders = _imports_under(_imported_modules(path), "src.eval")
    assert not offenders, f"{_module_name(path)} imports eval: {offenders}"
