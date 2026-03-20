# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Entry point for `python -m src.modules.management` CLI.

Delegates to the appropriate command module based on sys.argv.
"""

from __future__ import annotations

import sys

# Add project root to path so submodules are importable
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Also ensure 'src' parent is on path for `from src.modules.management` style imports
_src_parent = _project_root.parent
if str(_src_parent) not in sys.path:
    sys.path.insert(0, str(_src_parent))


def _resolve_subcommand() -> str:
    """Return the subcommand name from sys.argv, or empty string."""
    if len(sys.argv) < 2:
        return ""
    # If first arg looks like a flag, no subcommand given
    if sys.argv[1].startswith("-"):
        return ""
    return sys.argv[1]


def main() -> None:
    subcommand = _resolve_subcommand()

    if subcommand == "repair-articles":
        from modules.management.commands.repair_articles import main as repair_main

        # Strip the subcommand from sys.argv before delegating
        # sys.argv[0] = __main__.py path, sys.argv[1] = subcommand
        original_argv = sys.argv
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        try:
            repair_main()
        finally:
            sys.argv = original_argv
    elif subcommand == "help" or (len(sys.argv) > 1 and sys.argv[1] == "--help"):
        # Built-in help when no subcommand
        print("Available commands:")
        print("  repair-articles [--limit N] [--force] [--dry-run]")
        print("    Fix articles with NEO4J_DONE status but NULL enrichment fields.")
        print()
        print("Usage:")
        print(
            "  python -m src.modules.management repair-articles [--limit 10] [--force] [--dry-run]"
        )
        print()
        print("Examples:")
        print("  # Preview first 10 incomplete articles (dry run)")
        print("  python -m src.modules.management repair-articles --dry-run")
        print()
        print("  # Repair up to 10 articles")
        print("  python -m src.modules.management repair-articles --limit 10")
        print()
        print("  # Repair all incomplete articles (no Neo4j writes)")
        print("  python -m src.modules.management repair-articles --force")
        sys.exit(0)
    else:
        print(f"Unknown command: {subcommand}", file=sys.stderr)
        print("Run 'python -m src.modules.management --help' for usage.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
