# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Weaver E2E test package.

This package contains end-to-end tests that exercise the complete
application stack through the HTTP API.

E2E tests require Docker services (PostgreSQL, Neo4j, Redis) which
are managed by the fixtures in conftest.py.

Run with: pytest tests/e2e/ -v
"""
