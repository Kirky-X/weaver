# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Architectural guard: no runtime import cycles among modules/*.

Cross-module imports are allowed (module boundaries are enforced by the
container and protocols), but they must form a DAG. Deferred imports
(inside functions/methods) and TYPE_CHECKING blocks do not execute at
module import time and are therefore excluded — matching how import
cycles actually break applications.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULES = {
    "alert",
    "analytics",
    "briefing",
    "ingestion",
    "knowledge",
    "management",
    "memory",
    "processing",
    "scheduler",
    "search",
    "storage",
    "trend",
}

SRC_MODULES = Path(__file__).resolve().parents[2] / "src" / "modules"


def runtime_imports(path: Path) -> set[str]:
    """Collect module-scope cross-module imports (deferred/TYPE_CHECKING excluded)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()

    def walk_body(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("modules."):
                    mods.add(node.module)
            elif isinstance(node, ast.Import):
                mods.update(a.name for a in node.names if a.name.startswith("modules."))
            elif isinstance(node, ast.If):
                if "TYPE_CHECKING" not in ast.unparse(node.test):
                    walk_body(node.body)
                    walk_body(node.orelse)
            elif isinstance(node, ast.ClassDef):
                walk_body(node.body)
            # FunctionDef/AsyncFunctionDef bodies: deferred imports, skipped

    walk_body(tree.body)
    return mods


def _build_edges() -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for f in SRC_MODULES.rglob("*.py"):
        rel = f.relative_to(SRC_MODULES)
        parts = rel.parts
        if len(parts) < 2 or parts[0] not in MODULES:
            continue
        for mod in runtime_imports(f):
            ps = mod.split(".")
            if len(ps) > 1 and ps[1] in MODULES and ps[1] != parts[0]:
                edges.setdefault(parts[0], set()).add(ps[1])
    return edges


def _find_cycles(edges: dict[str, set[str]]) -> set[tuple[str, ...]]:
    cycles: set[tuple[str, ...]] = set()

    def dfs(start: str, cur: str, path: list[str], visited: set[str]) -> None:
        for nxt in sorted(edges.get(cur, ())):
            if nxt == start:
                cycles.add((*path, nxt))
            elif nxt not in visited:
                dfs(start, nxt, [*path, nxt], visited | {nxt})

    nodes = set(edges) | {x for v in edges.values() for x in v}
    for n in sorted(nodes):
        dfs(n, n, [n], {n})
    return cycles


def test_modules_import_graph_is_acyclic() -> None:
    edges = _build_edges()
    cycles = _find_cycles(edges)
    assert not cycles, (
        "Runtime import cycles detected among modules/* — break them by "
        "moving shared models to core/types, deferring imports, or using "
        f"TYPE_CHECKING for annotation-only deps. Cycles: {sorted(cycles)}"
    )


def test_expected_acyclic_edges_present() -> None:
    """Sanity: the detector is actually seeing cross-module edges."""
    edges = _build_edges()
    assert edges, "detector found no cross-module imports; check test logic"
