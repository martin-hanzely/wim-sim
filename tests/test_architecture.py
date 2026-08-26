"""Principle 6, enforced the same way principle 1 is.

> The estimator core stays dependency-light (numpy only) and framework-free so it can later be
> cross-deployed to a Raspberry Pi / Jetson unchanged. No MQTT, no database, no logging framework
> inside the estimator classes.

That is a claim about the import graph, so it is checked against the import graph rather than
trusted. The failure it prevents is mundane and near-certain without a test: someone adds a pydantic
model or a structlog call to an estimator for convenience, and eighteen months later the
cross-deployment story quietly no longer works.

``tests/test_truth_isolation.py`` covers the complementary rule for ``wimsim.signal``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

#: The estimator core. Must import nothing but the standard library, numpy, and wimsim.core.
DEPENDENCY_LIGHT = ("calibration",)

#: Everything a Raspberry Pi deployment should not need in order to compute a mass.
FORBIDDEN_THIRD_PARTY = {
    "pydantic",
    "pyarrow",
    "pandas",
    "yaml",
    "matplotlib",
    "typer",
    "click",
    "paho",
    "psycopg",
    "sqlalchemy",
    "alembic",
    "opentelemetry",
    "prometheus_client",
    "structlog",
    "loguru",
    "requests",
    "httpx",
}

ALLOWED_THIRD_PARTY = {"numpy"}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def _modules(src_root: Path, package: str) -> list[Path]:
    return sorted((src_root / package).rglob("*.py"))


@pytest.mark.parametrize("package", DEPENDENCY_LIGHT)
def test_estimator_core_imports_only_numpy_and_the_stdlib(src_root: Path, package: str) -> None:
    modules = _modules(src_root, package)
    assert modules, f"no modules found under {package}/ -- has the layout changed?"

    stdlib = set(sys.stdlib_module_names)
    for path in modules:
        for name in sorted(_top_level_imports(path)):
            if name in stdlib or name in ALLOWED_THIRD_PARTY or name == "wimsim":
                continue
            pytest.fail(
                f"{path.relative_to(src_root.parent)} imports {name!r}.\n"
                "Principle 6: the estimator core must stay numpy-only and framework-free so it can "
                "be cross-deployed to a Pi/Jetson unchanged. Convert at the edge instead: the "
                "pipeline builds transport models from EstimatorState, not the other way round."
            )


@pytest.mark.parametrize("package", DEPENDENCY_LIGHT)
def test_forbidden_dependencies_are_absent_at_runtime(package: str) -> None:
    """Catches deferred imports, which the AST walk above reports but a lazy import could hide."""
    code = (
        "import importlib, sys\n"
        f"importlib.import_module('wimsim.{package}')\n"
        f"forbidden = {sorted(FORBIDDEN_THIRD_PARTY)!r}\n"
        "print(';'.join(sorted(m for m in forbidden if m in sys.modules)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120
    )
    leaked = out.stdout.strip()
    assert not leaked, f"importing wimsim.{package} pulled in {leaked}"


@pytest.mark.parametrize("package", DEPENDENCY_LIGHT)
def test_estimator_core_depends_only_on_core_within_wimsim(src_root: Path, package: str) -> None:
    """``calibration`` may lean on ``wimsim.core`` for domain types and on nothing else.

    A dependency on ``edge`` or ``transport`` would invert the layering: infrastructure implements
    interfaces, not the reverse.
    """
    for path in _modules(src_root, package):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names if a.name.startswith("wimsim")]
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("wimsim")
            ):
                targets = [node.module]
            for target in targets:
                parts = target.split(".")
                if len(parts) < 2:
                    continue
                allowed = {"core", package}
                assert parts[1] in allowed, (
                    f"{path.relative_to(src_root.parent)} imports {target!r}; "
                    f"{package}/ may only depend on wimsim.core"
                )


def test_the_check_would_actually_fail(tmp_path: Path) -> None:
    """Negative control: plant a forbidden import and confirm the AST walk reports it."""
    fake = tmp_path / "wimsim"
    (fake / "calibration").mkdir(parents=True)
    (fake / "calibration" / "bad.py").write_text(
        "import pydantic\nfrom pydantic import BaseModel\n", encoding="utf-8"
    )
    with pytest.raises(BaseException):
        test_estimator_core_imports_only_numpy_and_the_stdlib(fake, "calibration")
