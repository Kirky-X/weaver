# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Shared helpers for per-domain endpoint E2E tests.

Every request goes through :func:`api_call` / :func:`api_call_multi`, which

1. performs the HTTP call,
2. strictly asserts the unified response envelope
   (``{code, message, data, timestamp}`` — success ``code == 0``,
   errors mapped from the HTTP status per ``api_response.py``),
3. records request/response/assertion outcome for the audit report.

Tests must assert exact status codes — no loose ``in [200, 400, 500]``
allow-lists: each endpoint's business contract is pinned by these tests.
For endpoints whose legitimate outcome depends on the environment
(e.g. 503 when the LLM stack is absent in fallback mode),
:func:`api_call_multi` asserts a strict contract *per possible status*.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.e2e.api_response_recorder import APIResponseRecorder

# HTTP status → business code mapping (src/api/middleware/api_response.py:22-30)
STATUS_TO_CODE = {
    400: 10001,
    401: 10002,
    403: 10003,
    404: 10004,
    409: 10005,
    422: 10001,
    503: 50001,
}
CODE_INTERNAL = 10099


def _resolve_code(status: int, expect_code: int | None) -> int:
    if expect_code is not None:
        return expect_code
    return 0 if 200 <= status < 300 else STATUS_TO_CODE.get(status, CODE_INTERNAL)


def _assert_envelope(
    test_case: str,
    body: Any,
    status: int,
    expect_code: int | None,
    expect_data: bool,
) -> None:
    assert body is not None, f"{test_case}: expected a JSON body for HTTP {status}"
    assert "timestamp" in body, f"{test_case}: envelope missing timestamp: {body}"
    assert "message" in body, f"{test_case}: envelope missing message: {body}"
    code = _resolve_code(status, expect_code)
    assert body.get("code") == code, (
        f"{test_case}: expected code {code}, got {body.get('code')} "
        f"(message: {body.get('message')})"
    )
    if code == 0 and expect_data:
        assert body.get("data") is not None, f"{test_case}: success envelope has null data"
    if code != 0:
        assert body.get("data") is None, f"{test_case}: error envelope must have null data"


def _request(
    client: TestClient,
    method: str,
    url: str,
    headers: dict[str, str] | None,
    params: dict[str, Any] | None,
    json_data: Any,
):
    request_kwargs: dict[str, Any] = {}
    if headers:
        request_kwargs["headers"] = headers
    if params:
        request_kwargs["params"] = params
    if json_data is not None:
        request_kwargs["json"] = json_data
    start = time.perf_counter()
    response = getattr(client, method.lower())(url, **request_kwargs)
    duration_ms = (time.perf_counter() - start) * 1000
    body = None
    if response.status_code not in (204, 304):
        body = response.json()
    return response, body, duration_ms


def _record(
    recorder: APIResponseRecorder,
    endpoint: str,
    method: str,
    url: str,
    headers: dict[str, str] | None,
    params: dict[str, Any] | None,
    json_data: Any,
    response,
    body: Any,
    duration_ms: float,
    test_case: str,
    validation: dict[str, Any],
) -> None:
    recorder.record(
        endpoint=endpoint,
        method=method,
        url=url,
        request_headers=headers,
        request_params=params,
        request_body=json_data,
        response_status=response.status_code,
        response_headers=dict(response.headers),
        response_body=body,
        duration_ms=duration_ms,
        test_case=test_case,
        validation_result=validation,
    )


def api_call(
    client: TestClient,
    recorder: APIResponseRecorder,
    method: str,
    url: str,
    endpoint: str,
    test_case: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_data: Any = None,
    expect_status: int = 200,
    expect_code: int | None = None,
    expect_data: bool = True,
    expect_envelope: bool = True,
) -> dict[str, Any] | None:
    """Call an endpoint, assert the envelope contract, record the exchange.

    Args:
        client: TestClient instance.
        recorder: Audit recorder.
        method: HTTP method.
        url: Request path.
        endpoint: Endpoint category for the audit record.
        test_case: Scenario name for the audit record.
        headers: Optional request headers.
        params: Optional query parameters.
        json_data: Optional JSON body.
        expect_status: Exact expected HTTP status code.
        expect_code: Exact expected business ``code``; defaults to the
            status-to-code mapping (0 for 2xx).
        expect_data: Whether a success envelope must carry non-null ``data``.
        expect_envelope: False for the saga endpoints that return bare dicts.

    Returns:
        Parsed response body (dict) or None for empty bodies.
    """
    response, body, duration_ms = _request(client, method, url, headers, params, json_data)

    # Exact status assertion — no allow-lists
    assert response.status_code == expect_status, (
        f"{test_case}: expected HTTP {expect_status}, got {response.status_code}: "
        f"{response.text[:500]}"
    )

    validation: dict[str, Any] = {"envelope": "passed"}
    if body is not None and expect_envelope:
        _assert_envelope(test_case, body, response.status_code, expect_code, expect_data)

    _record(
        recorder,
        endpoint,
        method,
        url,
        headers,
        params,
        json_data,
        response,
        body,
        duration_ms,
        test_case,
        validation,
    )
    return body


def api_call_multi(
    client: TestClient,
    recorder: APIResponseRecorder,
    method: str,
    url: str,
    endpoint: str,
    test_case: str,
    variants: dict[int, dict[str, Any]],
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_data: Any = None,
) -> dict[str, Any] | None:
    """Call an endpoint whose outcome legitimately depends on the environment.

    ``variants`` maps each acceptable status code to that status's exact
    expectations (``expect_code``/``expect_data``), so every branch is still
    strictly asserted — the audit record shows which branch was taken.
    """
    response, body, duration_ms = _request(client, method, url, headers, params, json_data)

    if response.status_code not in variants:
        _record(
            recorder,
            endpoint,
            method,
            url,
            headers,
            params,
            json_data,
            response,
            body,
            duration_ms,
            test_case,
            {"envelope": "failed", "error": f"unexpected status {response.status_code}"},
        )
        pytest.fail(
            f"{test_case}: got HTTP {response.status_code}, allowed "
            f"{sorted(variants)}: {response.text[:500]}"
        )

    expect = variants[response.status_code]
    validation: dict[str, Any] = {"envelope": "passed", "variant": response.status_code}
    if body is not None:
        _assert_envelope(
            test_case,
            body,
            response.status_code,
            expect.get("expect_code"),
            expect.get("expect_data", True),
        )

    _record(
        recorder,
        endpoint,
        method,
        url,
        headers,
        params,
        json_data,
        response,
        body,
        duration_ms,
        test_case,
        validation,
    )
    return body
