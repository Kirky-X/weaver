#!/usr/bin/env python3
"""Fix corrupted model_id values in article_vectors table.

This script identifies and repairs model_id values that were incorrectly
set to '6B' due to a parsing bug in _extract_embedding_model_id().

The bug caused "Qwen3-Embedding-0.6B" to be parsed as "6B" instead of
the full model name.

Usage:
    python scripts/fix_model_id.py --dry-run    # Preview changes
    python scripts/fix_model_id.py --execute    # Apply fixes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def fix_model_id_dry_run(db_url: str) -> None:
    """Preview the fixes without applying them."""
    import duckdb

    conn = duckdb.connect(db_url)

    print("=" * 60)
    print("DRY RUN - Previewing fixes")
    print("=" * 60)

    # Find corrupted model_ids
    query = """
        SELECT
            model_id,
            COUNT(*) as count,
            MIN(created_at) as first_seen,
            MAX(created_at) as last_seen
        FROM article_vectors
        GROUP BY model_id
        ORDER BY count DESC
    """

    result = conn.execute(query).fetchall()

    print("\nCurrent model_id distribution:")
    for model_id, count, first_seen, last_seen in result:
        print(f"  {model_id!r:40s} {count:6d} rows  ({first_seen} to {last_seen})")

    # Check for '6B' specifically
    query_6b = "SELECT COUNT(*) FROM article_vectors WHERE model_id = '6B'"
    count_6b = conn.execute(query_6b).fetchone()[0]

    if count_6b > 0:
        print(f"\n⚠ Found {count_6b} rows with corrupted model_id='6B'")
        print("  These will be updated to 'Qwen3-Embedding-0.6B'")

        # Show sample affected rows
        sample = conn.execute("""
            SELECT article_id, vector_type, created_at
            FROM article_vectors
            WHERE model_id = '6B'
            LIMIT 5
        """).fetchall()

        print("\n  Sample affected rows:")
        for article_id, vector_type, created_at in sample:
            print(f"    {article_id} | {vector_type} | {created_at}")
    else:
        print("\n✓ No corrupted model_id='6B' found")

    conn.close()


def fix_model_id_execute(db_url: str) -> None:
    """Apply the fixes to the database."""
    import duckdb

    conn = duckdb.connect(db_url)

    print("=" * 60)
    print("EXECUTING fixes")
    print("=" * 60)

    # Check for '6B' before fixing
    query_6b = "SELECT COUNT(*) FROM article_vectors WHERE model_id = '6B'"
    count_6b = conn.execute(query_6b).fetchone()[0]

    if count_6b == 0:
        print("✓ No corrupted model_id='6B' found. Nothing to fix.")
        conn.close()
        return

    print(f"\nFound {count_6b} rows with model_id='6B'")
    print("Updating to 'Qwen3-Embedding-0.6B'...")

    # Begin transaction
    conn.execute("BEGIN TRANSACTION")

    try:
        # Update corrupted model_id
        update_query = """
            UPDATE article_vectors
            SET model_id = 'Qwen3-Embedding-0.6B'
            WHERE model_id = '6B'
        """

        result = conn.execute(update_query)
        updated_count = result.fetchone()[0] if result else 0

        print(f"✓ Updated {updated_count} rows")

        # Verify the fix
        verify_query = "SELECT COUNT(*) FROM article_vectors WHERE model_id = '6B'"
        remaining = conn.execute(verify_query).fetchone()[0]

        if remaining == 0:
            print("✓ Verification passed: no more corrupted model_id='6B'")

            # Commit
            conn.execute("COMMIT")
            print("✓ Changes committed to database")
        else:
            print(f"✗ Verification failed: {remaining} rows still have model_id='6B'")
            conn.execute("ROLLBACK")
            print("✓ Changes rolled back")

    except Exception as e:
        print(f"✗ Error during update: {e}")
        conn.execute("ROLLBACK")
        print("✓ Changes rolled back due to error")
        raise

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Fix corrupted model_id values in article_vectors table"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="data/weaver.duckdb",
        help="Path to DuckDB database (default: data/weaver.duckdb)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying them"
    )
    parser.add_argument("--execute", action="store_true", help="Apply the fixes to the database")

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("Error: You must specify either --dry-run or --execute")
        parser.print_help()
        sys.exit(1)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)

    if args.dry_run:
        fix_model_id_dry_run(str(db_path))
    elif args.execute:
        print("⚠ This will modify the database. Continue? (y/n): ", end="")
        confirm = input().strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)
        fix_model_id_execute(str(db_path))


if __name__ == "__main__":
    main()
