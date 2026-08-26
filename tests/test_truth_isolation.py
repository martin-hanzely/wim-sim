"""Principle 1, enforced by the import graph.

"The estimator must be structurally incapable of reading ground truth." A comment saying so is not
a mechanism. These tests are the mechanism, and they are deliberately paranoid in two independent
ways:

* :func:`test_no_static_path_to_signal` walks the *transitive* first-party import graph. A direct
  ``import wimsim.signal.truth`` inside ``calibration/`` is the obvious violation and the easy one
  to catch; the dangerous one is a helper module that innocently imports the generator and then
  gets imported by an estimator three releases later. Reachability catches both.
* :func:`test_no_runtime_path_to_signal` imports the quarantined packages in a fresh interpreter and
  asserts ``wimsim.signal`` never appears in ``sys.modules``. This catches what AST analysis cannot:
  a deferred import inside a function body, an ``importlib.import_module`` with a computed name, a
  plugin loader.

Both must pass. Neither is sufficient alone.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

#: Packages that must never be able to reach ground truth. Every one of them is downstream of
#: SourceAdapter, and everything downstream of SourceAdapter sees measurements only.
QUARANTINED = ("calibration", "edge", "transport", "ingest", "storage", "observability")

#: The forbidden target.
FORBIDDEN_PREFIX = "wimsim.signal"


def _module_name(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports_of(path: Path) -> set[str]:
    """First-party module names imported by one file, including inside function bodies."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("wimsim"):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # relative imports are not used in this codebase; fail loudly rather than guess
                raise AssertionError(
                    f"{path}: relative import found; use absolute wimsim.* imports"
                )
            if node.module and node.module.startswith("wimsim"):
                found.add(node.module)
                for alias in node.names:
                    found.add(f"{node.module}.{alias.name}")
    return found


def _build_graph(src_root: Path) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in sorted(src_root.rglob("*.py")):
        graph[_module_name(path, src_root)] = _imports_of(path)
    return graph


def _resolve(target: str, graph: dict[str, set[str]]) -> str | None:
    """Map an imported name onto a module in the graph, dropping a trailing symbol if needed."""
    if target in graph:
        return target
    parent = target.rsplit(".", 1)[0]
    return parent if parent in graph else None


def test_no_static_path_to_signal(src_root: Path) -> None:
    graph = _build_graph(src_root)
    roots = [name for name in graph if any(f"wimsim.{p}" in name for p in QUARANTINED)]
    assert roots, "no quarantined modules found -- has the layout changed?"

    for root in roots:
        # breadth-first over first-party imports, recording how we got there
        stack: list[tuple[str, list[str]]] = [(root, [root])]
        seen = {root}
        while stack:
            module, trail = stack.pop()
            for target in sorted(graph.get(module, ())):
                if target.startswith(FORBIDDEN_PREFIX):
                    chain = " -> ".join([*trail, target])
                    pytest.fail(
                        f"{root} can reach ground truth: {chain}\n"
                        "Principle 1: the estimator must be structurally incapable of reading the "
                        "truth log. Move the shared code into wimsim.core instead."
                    )
                resolved = _resolve(target, graph)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    stack.append((resolved, [*trail, resolved]))


@pytest.mark.parametrize("package", QUARANTINED)
def test_no_runtime_path_to_signal(package: str) -> None:
    """Import the package in a fresh interpreter; wimsim.signal must not appear."""
    code = (
        "import importlib, sys\n"
        f"importlib.import_module('wimsim.{package}')\n"
        "leaked = sorted(m for m in sys.modules if m.startswith('wimsim.signal'))\n"
        "print(';'.join(leaked))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120
    )
    leaked = out.stdout.strip()
    assert not leaked, f"importing wimsim.{package} pulled in {leaked}"


def test_the_test_would_actually_fail(tmp_path: Path, src_root: Path) -> None:
    """Guard against a vacuous check: plant a violation and confirm the graph walk finds it."""
    fake = tmp_path / "wimsim"
    (fake / "calibration").mkdir(parents=True)
    (fake / "signal").mkdir()
    (fake / "__init__.py").write_text("", encoding="utf-8")
    (fake / "signal" / "__init__.py").write_text("", encoding="utf-8")
    (fake / "signal" / "truth.py").write_text("", encoding="utf-8")
    (fake / "calibration" / "__init__.py").write_text(
        "from wimsim.signal.truth import TruthLog\n", encoding="utf-8"
    )
    with pytest.raises(BaseException):  # pytest.fail raises Failed, not Exception
        test_no_static_path_to_signal(fake)
