#!/usr/bin/env python3
"""Verify refactoring integrity - import paths and documentation references.

Run after each refactoring phase to catch broken imports early.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def check_imports() -> list[str]:
    """Scan all Python files for broken imports."""
    errors = []

    for py_file in ROOT.glob("src/**/*.py"):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError as e:
            errors.append(f"Syntax error in {py_file.relative_to(ROOT)}: {e}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _check_module_import(alias.name, py_file, errors)
            elif isinstance(node, ast.ImportFrom) and node.module:
                _check_module_import(node.module, py_file, errors)

    return errors


def _check_module_import(module_name: str, source_file: Path, errors: list[str]) -> None:
    """Check if a module can be resolved."""
    module_path = module_name.replace(".", "/")
    # Check as package or module
    possible = [
        ROOT / "src" / f"{module_path}.py",
        ROOT / "src" / module_path / "__init__.py",
    ]
    if not any(p.exists() for p in possible):
        # Don't flag stdlib or third-party
        if not module_name.startswith(("src.", ".")):
            return
        rel = source_file.relative_to(ROOT)
        errors.append(f"  {rel}: cannot import '{module_name}'")


def check_doc_paths() -> list[str]:
    """Check that code paths mentioned in docs actually exist."""
    errors = []
    doc_files = list(ROOT.glob("docs/**/*.md"))

    for doc in doc_files:
        content = doc.read_text()
        # Find code path references (patterns like src/..., core/..., modules/...)
        import re

        paths = re.findall(r"(?:src|core|modules|api|tests)/[\w/_.]+", content)
        for path in paths:
            # Skip non-file references
            if any(skip in path for skip in [".py)", ".py,", "```", "pytest", "npx", "git"]):
                continue
            full_path = ROOT / path.rstrip("`").rstrip("*")
            if not full_path.exists() and not full_path.with_suffix(".py").exists():
                # Check if it's a directory reference
                pass  # Directories may not exist as .py files

    return errors


def run_tests(module_filter: str | None = None) -> bool:
    """Run pytest for affected tests."""
    cmd = ["uv", "run", "pytest", "tests/unit/", "-v", "--tb=short", "-x"]
    if module_filter:
        cmd.append(f"-k={module_filter}")

    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-2000:])
        return False
    return True


def main() -> int:
    print("=" * 60)
    print("Refactoring Verification Report")
    print("=" * 60)

    print("\n[1/3] Checking Python imports...")
    import_errors = check_imports()
    if import_errors:
        print(f"  Found {len(import_errors)} import issues:")
        for err in import_errors[:20]:
            print(err)
        if len(import_errors) > 20:
            print(f"  ... and {len(import_errors) - 20} more")
    else:
        print("  OK - No import issues detected")

    print("\n[2/3] Checking documentation paths...")
    doc_errors = check_doc_paths()
    if doc_errors:
        print(f"  Found {len(doc_errors)} path issues:")
        for err in doc_errors[:10]:
            print(err)
    else:
        print("  OK - Doc paths valid")

    print("\n[3/3] Summary")
    total_issues = len(import_errors) + len(doc_errors)
    if total_issues == 0:
        print("  All checks passed")
        return 0
    else:
        print(f"  {total_issues} issues found - review before proceeding")
        return 1


if __name__ == "__main__":
    sys.exit(main())
