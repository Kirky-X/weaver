# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Guard: ladybug_schema NODE_TABLES/REL_TABLES stay in sync with SCHEMA_QUERIES.

The vocabulary tuples are the single source consumed by scripts/data_io.py
and scripts/db.py; the DDL list (SCHEMA_QUERIES) is the schema authority.
These tests fail when a table is added to one place but not the other.
"""

from __future__ import annotations

import re

from core.db.ladybug_schema import NODE_TABLES, REL_TABLES, SCHEMA_QUERIES


def _extract_table_names(ddl_pattern: str) -> set[str]:
    names = set()
    for query in SCHEMA_QUERIES:
        m = re.match(ddl_pattern, query.strip())
        if m:
            names.add(m.group(1))
    return names


class TestLadybugSchemaVocabulary:
    def test_node_tables_match_ddl(self) -> None:
        ddl_nodes = _extract_table_names(r"CREATE NODE TABLE (?:IF NOT EXISTS )?(\w+) \(")
        assert ddl_nodes == set(NODE_TABLES), (
            f"NODE_TABLES drift: DDL={sorted(ddl_nodes)} vs constant={sorted(NODE_TABLES)}"
        )

    def test_rel_tables_match_ddl(self) -> None:
        ddl_rels = _extract_table_names(r"CREATE REL TABLE (?:IF NOT EXISTS )?(\w+) \(")
        assert ddl_rels == set(REL_TABLES), (
            f"REL_TABLES drift: DDL={sorted(ddl_rels)} vs constant={sorted(REL_TABLES)}"
        )

    def test_no_duplicate_entries(self) -> None:
        assert len(NODE_TABLES) == len(set(NODE_TABLES))
        assert len(REL_TABLES) == len(set(REL_TABLES))
