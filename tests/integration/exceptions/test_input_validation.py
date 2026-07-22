# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Input validation integration tests (V-01 ~ V-15).

Covers 15 input validation cases across five endpoint groups:
- Search params (V-01~V-05): q, community_level, threshold, limit
- Articles params (V-06~V-08): page, sort_by, UUID format
- Source URL validation (V-09): RFC 1035 label length
- Graph params (V-10~V-12): max_depth, max_hops, Cypher injection
- Monitoring/Briefings params (V-13~V-15): saga limit, alert rule_id,
  briefing category

Conflict notes (规则4 — exposed, not silently resolved):
1. V-02: ``q`` has ``min_length=1`` but NO ``max_length``. A 1001-char
   query passes validation and reaches the handler. Documented as actual
   behavior (not 422).
2. V-03: Task spec says ``community_level=10`` is out-of-bounds (>5),
   but the actual constraint is ``ge=0, le=10`` (inclusive). 10 is VALID.
   Using ``community_level=11`` to trigger the real boundary.
3. V-07: ``sort_by`` uses a whitelist with SILENT FALLBACK to
   ``publish_time`` (articles.py line 242-243), NOT a 422 rejection.
   Invalid values are silently replaced — a security concern documented
   in the test.
4. V-11: GET /graph/visualization has no ``max_hops`` query param (only
   ``limit``). ``max_hops`` lives in the POST body (SubgraphRequest).
   Testing POST with body to exercise the actual constraint.
5. V-12: POST /graph/traverse has no free-form ``query`` field. All
   Cypher is parameterized via ``graph_repo.traverse()``. A malicious
   ``start_entity`` string is treated as a literal entity name, not
   executed as Cypher. Injection is prevented by design (parameterized
   queries), not by input rejection.
6. V-13: Actual path is ``/api/v1/saga/failed/list`` (saga router
   prefix="/saga"), NOT ``/api/v1/monitoring/saga/failures`` as stated
   in the task spec.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


# ── V-01~V-05: Search Parameter Validation ─────────────────────


@pytest.mark.asyncio
async def test_v01_empty_query(async_client):
    """V-01: Empty search query returns 422.

    GET /api/v1/search?q= — q has ``min_length=1`` (search.py line 115).
    FastAPI rejects the empty string before reaching the handler.
    """
    resp = await async_client.get("/api/v1/search?q=")
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "q" in detail_str


@pytest.mark.asyncio
async def test_v02_oversized_query(async_client):
    """V-02: Query exceeding 1000 characters — no max_length constraint.

    Conflict: ``q`` is declared as ``Query(..., min_length=1)`` with no
    ``max_length`` (search.py line 115). FastAPI does NOT reject long
    queries. A 1001-char string passes validation and reaches the handler.
    The response is 200 (search succeeds) or 500 (downstream service
    error), but NOT 422 from length validation.

    Security note: absent max_length allows unbounded query strings,
    which could strain embedding/LLM downstream services.
    """
    long_q = "a" * 1001
    resp = await async_client.get(f"/api/v1/search?q={long_q}")
    # No length validation → not 422 from q length check
    assert resp.status_code != 422


@pytest.mark.asyncio
async def test_v03_community_level_out_of_range(async_client):
    """V-03: community_level out of range returns 422.

    Conflict: Task spec says ``community_level=10`` is out-of-bounds
    (>5), but the actual constraint is ``ge=0, le=10`` (search.py
    line 120). 10 is VALID. Using ``community_level=11`` to trigger
    the actual boundary (le=10 → 11 is rejected).
    """
    resp = await async_client.get("/api/v1/search?q=test&community_level=11")
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "community_level" in detail_str


@pytest.mark.asyncio
async def test_v04_threshold_out_of_range(async_client):
    """V-04: threshold > 1.0 returns 422.

    GET /api/v1/search?q=test&threshold=1.5 — threshold has
    ``ge=0.0, le=1.0`` (search.py line 121-123).
    """
    resp = await async_client.get("/api/v1/search?q=test&threshold=1.5")
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "threshold" in detail_str


@pytest.mark.asyncio
async def test_v05_limit_out_of_range(async_client):
    """V-05: limit > 100 returns 422.

    GET /api/v1/search?q=test&limit=1000 — limit has
    ``ge=1, le=100`` (search.py line 124).
    """
    resp = await async_client.get("/api/v1/search?q=test&limit=1000")
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "limit" in detail_str


# ── V-06~V-08: Articles Parameter Validation ───────────────────


@pytest.mark.asyncio
async def test_v06_page_out_of_range(async_client):
    """V-06: page < 1 returns 422.

    GET /api/v1/articles?page=0 — page has ``ge=1`` (articles.py
    line 158).
    """
    resp = await async_client.get("/api/v1/articles?page=0")
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "page" in detail_str


@pytest.mark.asyncio
async def test_v07_sort_by_not_whitelisted(async_client):
    """V-07: Non-whitelisted sort_by — silent fallback, NOT 422.

    Conflict: Task spec expects 422, but articles.py line 241-243
    silently falls back to ``publish_time`` when ``sort_by`` is not in
    ``ALLOWED_SORT_COLUMNS``::

        if sort_by not in ALLOWED_SORT_COLUMNS:
            sort_by = "publish_time"

    The invalid value is NOT rejected — it's silently replaced. This is
    a security concern: invalid input should be rejected (422), not
    silently ignored. The test verifies the actual behavior (not 422).
    """
    resp = await async_client.get("/api/v1/articles?sort_by=malicious_column")
    # NOT 422 — invalid sort_by silently falls back to "publish_time"
    assert resp.status_code != 422


@pytest.mark.asyncio
async def test_v08_invalid_uuid_format(async_client):
    """V-08: Invalid UUID format returns 400.

    GET /api/v1/articles/not-a-uuid — ``article_id`` is a ``str`` path
    parameter (not a UUID type). UUID validation happens in the handler
    via ``uuid.UUID(article_id)`` → ``ValueError`` → ``HTTPException``
    with status 400 (articles.py line 299-305).
    """
    resp = await async_client.get("/api/v1/articles/not-a-uuid")
    assert resp.status_code == 400
    assert "Invalid article ID format" in resp.json().get("message", "")


# ── V-09: Source URL RFC 1035 Validation ────────────────────────


@pytest.mark.asyncio
async def test_v09_rfc1035_label_too_long(async_client):
    """V-09: RFC 1035 hostname label exceeding 63 chars returns 422.

    POST /api/v1/sources with a URL whose hostname label is 64 chars.
    ``SourceCreateRequest.url`` has a ``@field_validator`` that calls
    ``_validate_source_url()`` (sources.py line 87-91). Labels > 63
    chars raise ``ValueError`` → Pydantic 422.

    The 64-char label is all ``a`` characters (valid charset, just too
    long). The field_validator runs during Pydantic validation, before
    the handler — so no HTTP fetch or SSRF check is performed.
    """
    long_label = "a" * 64  # 64 chars, exceeds RFC 1035 limit of 63
    body = {
        "id": "test-rfc1035-validation",
        "name": "RFC 1035 Test Source",
        "url": f"http://{long_label}.com/feed.xml",
    }
    resp = await async_client.post("/api/v1/sources", json=body)
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "label" in detail_str.lower() or "url" in detail_str.lower()


# ── V-10~V-12: Graph Parameter Validation ───────────────────────


@pytest.mark.asyncio
async def test_v10_traverse_max_depth_out_of_range(async_client):
    """V-10: traverse max_depth > 6 returns 422.

    POST /api/v1/graph/traverse — ``TraverseRequest.max_depth`` has
    ``ge=1, le=6`` (traverse.py line 30). max_depth=100 is rejected.
    """
    body = {"start_entity": "test_entity", "max_depth": 100}
    resp = await async_client.post("/api/v1/graph/traverse", json=body)
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "max_depth" in detail_str


@pytest.mark.asyncio
async def test_v11_visualization_max_hops_out_of_range(async_client):
    """V-11: visualization max_hops > 4 returns 422.

    Conflict: Task spec says ``GET /api/v1/graph/visualization?max_hops=1000``,
    but the GET endpoint has no ``max_hops`` query param (only ``limit``).
    ``max_hops`` lives in the POST body via ``SubgraphRequest`` with
    ``Field(2, ge=1, le=4)`` (graph_visualization.py line 72).

    Testing POST with body ``max_hops=1000`` to exercise the actual
    constraint. On the GET endpoint, ``max_hops`` as a query param would
    be silently ignored by FastAPI (unknown query params are ignored).
    """
    body = {"center_entity": "test_entity", "max_hops": 1000}
    resp = await async_client.post("/api/v1/graph/visualization", json=body)
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "max_hops" in detail_str


@pytest.mark.asyncio
async def test_v12_cypher_injection_prevention(async_client):
    """V-12: Cypher injection attempt is safely handled.

    Conflict: Task spec expects 422/400 for a query containing
    ``MATCH (n) DELETE n``. However, POST /graph/traverse has no
    free-form ``query`` field — ``TraverseRequest`` only accepts
    structured fields (start_entity, max_depth, relation_types, etc.).
    All Cypher is parameterized via ``graph_repo.traverse()``.

    The malicious string ``"MATCH (n) DELETE n"`` is sent as
    ``start_entity``. It passes validation (min_length=1, no pattern
    restriction) and is used as a **literal parameter value** in the
    Cypher query (e.g., ``WHERE e.canonical_name = $start_entity``),
    NOT as raw Cypher code. The graph DB looks for an entity with that
    name, finds none, and returns empty results (200) — no deletion
    occurs.

    Injection is prevented by design (parameterized queries), not by
    input validation rejection. The test verifies:
    1. The malicious string is NOT rejected (not 422 from validation).
    2. The response indicates safe handling (200 with empty results or
       500 from DB issues — neither indicates Cypher execution).
    """
    malicious_entity = "MATCH (n) DELETE n"
    body = {"start_entity": malicious_entity, "max_depth": 3}
    resp = await async_client.post("/api/v1/graph/traverse", json=body)
    # Validation passes — the string is a valid entity name
    assert resp.status_code != 422
    # Handled safely: 200 (entity not found, empty results) or 500 (DB
    # error). Neither status indicates Cypher injection execution.
    assert resp.status_code in (200, 500)


# ── V-13~V-15: Monitoring & Briefings Validation ───────────────


@pytest.mark.asyncio
async def test_v13_saga_limit_out_of_range(async_client):
    """V-13: saga failed-list limit > 200 returns 422.

    Conflict: Task spec says path is ``/api/v1/monitoring/saga/failures``,
    but the actual path is ``/api/v1/saga/failed/list`` (saga router
    prefix="/saga", endpoint "/failed/list" — saga.py line 199).

    The ``limit`` parameter has ``ge=1, le=200`` (saga.py line 201).
    limit=10000 is rejected.
    """
    resp = await async_client.get("/api/v1/saga/failed/list?limit=10000")
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "limit" in detail_str


@pytest.mark.asyncio
async def test_v14_alert_trigger_missing_rule_id(async_client):
    """V-14: POST /monitoring/alerts/trigger without rule_id returns 422.

    ``TriggerAlertRequest`` declares ``rule_id`` and ``metric_value`` as
    required fields (``Field(...)`` — alerts.py line 61-62). Sending an
    empty body ``{}`` fails Pydantic validation with 422 for both
    missing fields.
    """
    resp = await async_client.post("/api/v1/monitoring/alerts/trigger", json={})
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "rule_id" in detail_str


@pytest.mark.asyncio
async def test_v15_briefing_category_invalid(async_client):
    """V-15: POST /briefings/daily/generate with invalid category returns 422.

    The ``category`` query parameter has ``pattern=_CATEGORY_PATTERN``
    which is ``^(finance|tech|ai|general)$`` (briefings.py line 49,
    line 197-201). ``category=invalid`` does not match → 422.
    """
    resp = await async_client.post("/api/v1/briefings/daily/generate?category=invalid")
    assert resp.status_code == 422
    detail_str = str(resp.json().get("message", ""))
    assert "category" in detail_str
