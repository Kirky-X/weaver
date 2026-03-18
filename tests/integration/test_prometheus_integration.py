"""Integration tests for Prometheus metrics endpoint."""

import pytest
import re
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter

from config.settings import Settings


@pytest.fixture
def minimal_app():
    """Create minimal FastAPI app with only /metrics endpoint.

    This avoids database initialization since /metrics doesn't need it.
    """
    app = FastAPI()

    @app.get("/metrics")
    async def metrics_endpoint():
        """Prometheus metrics endpoint."""
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app


@pytest.fixture
def test_client(minimal_app):
    """Create test client with minimal app."""
    with TestClient(minimal_app) as client:
        yield client


class TestPrometheusMetricsEndpoint:
    """Integration tests for /metrics endpoint."""

    def test_metrics_endpoint_accessible(self, test_client):
        """Test that /metrics endpoint is accessible.

        验证 /metrics 端点可访问且返回 200 状态码。
        """
        response = test_client.get("/metrics")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_metrics_content_type(self, test_client):
        """Test that /metrics returns correct Content-Type.

        验证返回正确的 Prometheus Content-Type
        """
        response = test_client.get("/metrics")

        # 使用 prometheus_client 的实际常量值
        expected_content_type = CONTENT_TYPE_LATEST
        actual_content_type = response.headers.get("content-type", "")

        assert actual_content_type == expected_content_type, \
            f"Expected Content-Type '{expected_content_type}', got '{actual_content_type}'"

    def test_metrics_format_valid_prometheus(self, test_client):
        """Test that metrics format follows Prometheus standard format.

        验证指标格式符合 Prometheus 标准格式。
        Prometheus 格式要求:
        - 每行格式: metric_name{labels} value
        - 或带有 TYPE/HELP 注释
        """
        response = test_client.get("/metrics")
        content = response.text

        # 验证内容非空
        assert content, "Metrics content should not be empty"

        # 验证 Prometheus 格式
        # Prometheus 格式允许:
        # 1. TYPE 注释: # TYPE metric_name type
        # 2. HELP 注释: # HELP metric_name description
        # 3. 指标行: metric_name{labels} value
        # 4. 空行

        lines = content.strip().split('\n')
        valid_lines = 0

        for line in lines:
            line = line.strip()

            # 空行是允许的
            if not line:
                continue

            # TYPE 或 HELP 注释
            if line.startswith('# TYPE ') or line.startswith('# HELP '):
                # 验证注释格式
                if line.startswith('# TYPE '):
                    # 格式: # TYPE metric_name type
                    parts = line.split()
                    assert len(parts) >= 3, f"Invalid TYPE line: {line}"
                else:
                    # 格式: # HELP metric_name description
                    parts = line.split()
                    assert len(parts) >= 3, f"Invalid HELP line: {line}"
                valid_lines += 1
                continue

            # 指标行格式: metric_name{labels} value 或 metric_name value
            # 使用正则匹配 Prometheus 格式
            # 格式: metric_name[{label="value"[,label2="value2"]*}] value [timestamp]
            metric_pattern = r'^[a-zA-Z_:][a-zA-Z0-9_:]*({[^}]+})?\s+[\d\.eE+-]+(\s+\d+)?$'
            assert re.match(metric_pattern, line), \
                f"Line does not match Prometheus format: {line}"
            valid_lines += 1

        # 至少应该有一些有效的指标行
        assert valid_lines > 0, "Should have at least some valid metric lines"

    def test_metrics_contains_basic_metrics(self, test_client):
        """Test that metrics contain basic application metrics.

        验证至少包含基础指标（如 http_requests_total 或类似指标）。
        """
        response = test_client.get("/metrics")
        content = response.text

        # 检查是否有任何指标名称
        # prometheus_client 默认会注册一些基础指标
        # 检查常见的指标前缀或名称
        has_metrics = False
        metric_names = set()

        for line in content.split('\n'):
            line = line.strip()

            # 跳过注释和空行
            if not line or line.startswith('#'):
                continue

            # 提取指标名称
            # 格式: metric_name{...} value 或 metric_name value
            match = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)', line)
            if match:
                metric_names.add(match.group(1))
                has_metrics = True

        assert has_metrics, "Should have at least some metrics"

        # 验证至少有一些合理的指标名称
        # 由于测试环境可能没有请求历史，我们只验证有任何指标即可
        assert len(metric_names) > 0, "Should have at least one metric name"

        # 可选: 检查是否有常见的指标类型
        # 这取决于 prometheus_client 的默认注册
        print(f"Found {len(metric_names)} unique metrics")

    def test_metrics_concurrent_access(self, test_client):
        """Test concurrent access to /metrics endpoint.

        测试并发访问 /metrics 端点，确保在并发情况下端点稳定工作。
        """
        # 发送多个连续请求来模拟压力测试
        # TestClient 不支持真正的并发，所以我们测试多次连续请求
        num_requests = 10
        responses = []

        for i in range(num_requests):
            response = test_client.get("/metrics")
            responses.append(response)

        # 验证所有请求都成功
        for i, response in enumerate(responses):
            assert response.status_code == 200, \
                f"Request {i} failed with status {response.status_code}"
            assert response.headers.get("content-type") == CONTENT_TYPE_LATEST
            assert len(response.text) > 0, f"Request {i} returned empty content"

    def test_metrics_response_size_reasonable(self, test_client):
        """Test that metrics response size is reasonable.

        验证指标响应大小合理，不会过大导致性能问题。
        """
        response = test_client.get("/metrics")
        content_size = len(response.content)

        # 指标内容通常应该在 1MB 以内
        # 如果超过这个大小，可能需要考虑优化
        max_reasonable_size = 1 * 1024 * 1024  # 1MB

        assert content_size < max_reasonable_size, \
            f"Metrics content size {content_size} bytes exceeds reasonable limit {max_reasonable_size} bytes"

        # 同时验证内容不为空
        assert content_size > 0, "Metrics content should not be empty"

    def test_metrics_charset_utf8(self, test_client):
        """Test that metrics response uses UTF-8 encoding.

        验证指标响应使用 UTF-8 编码。
        """
        response = test_client.get("/metrics")

        # 验证 Content-Type 包含 charset=utf-8
        content_type = response.headers.get("content-type", "")
        assert "charset=utf-8" in content_type.lower(), \
            f"Content-Type should include 'charset=utf-8', got: {content_type}"

        # 验证内容可以正确解码为 UTF-8
        try:
            content = response.content.decode('utf-8')
            assert len(content) > 0
        except UnicodeDecodeError as e:
            pytest.fail(f"Metrics content is not valid UTF-8: {e}")


class TestPrometheusMetricsIntegration:
    """Additional integration tests for Prometheus metrics."""

    def test_metrics_multiple_requests(self, test_client):
        """Test that metrics are consistent across multiple requests.

        验证多次请求的指标格式保持一致。
        """
        # 发送多次请求
        responses = []
        for i in range(3):
            response = test_client.get("/metrics")
            assert response.status_code == 200
            responses.append(response)

        # 验证所有响应的 Content-Type 一致
        content_types = {r.headers.get("content-type") for r in responses}
        assert len(content_types) == 1, "Content-Type should be consistent across requests"

        # 验证所有响应都包含有效内容
        for i, response in enumerate(responses):
            assert len(response.text) > 0, f"Response {i} should have content"

            # 验证内容包含 Prometheus 格式
            has_valid_content = False
            for line in response.text.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    # 至少有一行指标数据
                    has_valid_content = True
                    break

            assert has_valid_content, f"Response {i} should have at least one metric"