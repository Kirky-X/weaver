# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""One-shot bootstrap for a fresh weaver development environment.

Copies example configuration files (never overwriting existing ones),
prints the spaCy model install commands, and optionally runs database
migrations. Use ``--check`` to preview the planned actions without
touching the filesystem.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# (source, destination) pairs copied when the destination is missing
_CONFIG_COPIES = [
    ("config/settings.example.toml", "config/settings.toml"),
    ("config/llm.example.toml", "config/llm.toml"),
    (".env.example", ".env"),
]

_SPACY_COMMANDS = (
    'uv pip install "spacy-pkuseg>=0.0.27,<0.1.0"',
    "uv run python -m spacy download zh_core_web_lg",
)


def _copy_configs(check_only: bool) -> int:
    """Copy missing config files; return the number of copies needed."""
    copied = 0
    for source_rel, dest_rel in _CONFIG_COPIES:
        source = PROJECT_ROOT / source_rel
        dest = PROJECT_ROOT / dest_rel
        if dest.exists():
            print(f"  [skip] {dest_rel} already exists")
            continue
        if not source.exists():
            print(f"  [warn] template missing: {source_rel}")
            continue
        copied += 1
        if check_only:
            print(f"  [plan] copy {source_rel} -> {dest_rel}")
        else:
            shutil.copyfile(source, dest)
            print(f"  [done] copy {source_rel} -> {dest_rel}")
    return copied


def _print_spacy_hint() -> None:
    print("\nspaCy 模型（一次性，约 600MB）：")
    for command in _SPACY_COMMANDS:
        print(f"  {command}")


def _run_migrations(check_only: bool) -> bool:
    """Run alembic migrations unless check-only; return success."""
    alembic_ini = PROJECT_ROOT / "alembic.ini"
    if not alembic_ini.exists():
        print("  [warn] alembic.ini not found; skipping migrations")
        return True
    if check_only:
        print("  [plan] alembic upgrade head")
        return True
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("  [fail] migration failed; fix the error above and re-run")
        return False
    print("  [done] database migrations applied")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="dry-run: print planned actions without modifying files",
    )
    parser.add_argument(
        "--with-migrations",
        action="store_true",
        help="also run 'alembic upgrade head' after copying configs",
    )
    args = parser.parse_args(argv)

    print("weaver bootstrap" + (" (dry-run)" if args.check else ""))
    print("\n1. 配置文件（已存在的不会被覆盖）：")
    _copy_configs(check_only=args.check)
    _print_spacy_hint()

    if args.with_migrations:
        print("\n2. 数据库迁移：")
        if not _run_migrations(check_only=args.check):
            return 1

    print("\n后续步骤：")
    print("  docker compose -f docker/docker-compose.yml up -d   # 基础设施")
    print("  uv run uvicorn src.main:get_app --factory --reload  # 启动 API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
