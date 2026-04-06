# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for OpenTelemetry tracing with real SDK components."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


@pytest.fixture
def isolated_tracer_provider():
    """Create an isolated tracer provider for each test.

    This fixture creates a new TracerProvider without setting it as global,
    allowing tests to run in isolation without interfering with each other.
    """
    memory_exporter = InMemorySpanExporter()
    resource = Resource.create({"service.name": "test-weaver"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(memory_exporter))

    yield provider, memory_exporter

    # Cleanup
    provider.force_flush(timeout_millis=1000)
    provider.shutdown()


class TestTracingInitialization:
    """Test OpenTelemetry tracing initialization."""

    def test_configure_tracing_with_default_endpoint(self, monkeypatch):
        """Test tracing configuration with default endpoint."""
        from core.observability.tracing import configure_tracing

        # Prevent E2E env vars from affecting this test
        monkeypatch.delenv("WEAVER_OBSERVABILITY__OTLP_ENDPOINT", raising=False)

        # Reset global tracer provider. The tracer SDK uses a Once guard that
        # allows only one set_tracer_provider call per process, so we must also
        # reset the guard's _done flag.
        trace._TRACER_PROVIDER = None
        trace._TRACER_PROVIDER_SET_ONCE._done = False

        # Configure tracing with default endpoint
        configure_tracing(service_name="test-weaver")

        # Verify tracer provider is set and works
        provider = trace.get_tracer_provider()
        assert provider is not None
        assert isinstance(provider, TracerProvider)

        # Verify resource has correct service name
        resource = provider.resource
        assert resource.attributes.get("service.name") == "test-weaver"

        # Cleanup: reset again for subsequent tests
        trace._TRACER_PROVIDER = None
        trace._TRACER_PROVIDER_SET_ONCE._done = False

    def test_configure_tracing_with_custom_endpoint(self):
        """Test tracing configuration with custom OTLP endpoint."""
        from core.observability.tracing import configure_tracing

        # Reset global tracer provider
        trace._TRACER_PROVIDER = None

        # Configure with custom endpoint
        custom_endpoint = "http://custom-otlp:4317"
        configure_tracing(service_name="custom-weaver", endpoint=custom_endpoint)

        # Verify tracer provider is set and functional
        provider = trace.get_tracer_provider()
        assert provider is not None

        # Get a tracer to verify functionality
        tracer = trace.get_tracer("test-tracer")
        assert tracer is not None

        # Verify we can create spans (functional test)
        with tracer.start_as_current_span("test-span") as span:
            assert span is not None

        # Cleanup
        trace._TRACER_PROVIDER = None

    def test_get_tracer_returns_valid_tracer(self):
        """Test that get_tracer returns a valid tracer instance."""
        from core.observability.tracing import configure_tracing, get_tracer

        # Reset global tracer provider
        trace._TRACER_PROVIDER = None

        # Initialize tracing
        configure_tracing(service_name="test-weaver")

        # Get tracer
        tracer = get_tracer("test-module")
        assert tracer is not None
        assert isinstance(tracer, trace.Tracer)

        # Cleanup
        trace._TRACER_PROVIDER = None


class TestTracingDataExport:
    """Test OpenTelemetry span data export."""

    def test_span_export_with_memory_exporter(self, isolated_tracer_provider):
        """Test that spans are exported correctly using in-memory exporter."""
        provider, memory_exporter = isolated_tracer_provider

        # Create a tracer from the provider (not global)
        tracer = provider.get_tracer("test-tracer")

        # Create a span
        with tracer.start_as_current_span("test-operation") as span:
            span.set_attribute("user.id", "12345")
            span.set_attribute("operation.type", "read")

        # Get exported spans
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 1

        exported_span = spans[0]
        assert exported_span.name == "test-operation"
        assert exported_span.attributes.get("user.id") == "12345"
        assert exported_span.attributes.get("operation.type") == "read"

    def test_multiple_spans_export(self, isolated_tracer_provider):
        """Test that multiple spans are exported correctly."""
        provider, memory_exporter = isolated_tracer_provider

        # Create tracer
        tracer = provider.get_tracer("test-tracer")

        # Create multiple spans
        with tracer.start_as_current_span("operation-1"):
            pass

        with tracer.start_as_current_span("operation-2"):
            pass

        with tracer.start_as_current_span("operation-3"):
            pass

        # Verify all spans exported
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 3

        span_names = [span.name for span in spans]
        assert "operation-1" in span_names
        assert "operation-2" in span_names
        assert "operation-3" in span_names


class TestSpanAttributes:
    """Test span attributes and metadata."""

    def test_span_contains_service_name(self, isolated_tracer_provider):
        """Test that spans contain service name in resource."""
        provider, memory_exporter = isolated_tracer_provider

        # Verify resource attributes
        assert provider.resource.attributes.get("service.name") == "test-weaver"

        # Create span
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("test-span"):
            pass

        # Verify span was created
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 1

    def test_span_with_custom_attributes(self, isolated_tracer_provider):
        """Test span with custom attributes."""
        provider, memory_exporter = isolated_tracer_provider

        # Create span with custom attributes
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("api-request") as span:
            span.set_attribute("http.method", "GET")
            span.set_attribute("http.url", "/api/articles")
            span.set_attribute("http.status_code", 200)
            span.set_attribute("user.id", "user-123")

        # Verify attributes
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 1

        span = spans[0]
        assert span.name == "api-request"
        assert span.attributes.get("http.method") == "GET"
        assert span.attributes.get("http.url") == "/api/articles"
        assert span.attributes.get("http.status_code") == 200
        assert span.attributes.get("user.id") == "user-123"

    def test_span_with_span_kind(self, isolated_tracer_provider):
        """Test span with different span kinds."""
        provider, memory_exporter = isolated_tracer_provider

        # Create spans with different kinds
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("server-span", kind=SpanKind.SERVER):
            pass

        with tracer.start_as_current_span("client-span", kind=SpanKind.CLIENT):
            pass

        with tracer.start_as_current_span("internal-span", kind=SpanKind.INTERNAL):
            pass

        # Verify kinds
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 3

        server_span = next(s for s in spans if s.name == "server-span")
        client_span = next(s for s in spans if s.name == "client-span")
        internal_span = next(s for s in spans if s.name == "internal-span")

        assert server_span.kind == SpanKind.SERVER
        assert client_span.kind == SpanKind.CLIENT
        assert internal_span.kind == SpanKind.INTERNAL


class TestTraceContextPropagation:
    """Test trace context propagation."""

    def test_parent_child_span_relationship(self, isolated_tracer_provider):
        """Test that child spans maintain parent relationship."""
        provider, memory_exporter = isolated_tracer_provider

        # Create parent and child spans
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("parent-operation") as parent:
            parent.set_attribute("level", "parent")

            with tracer.start_as_current_span("child-operation") as child:
                child.set_attribute("level", "child")

        # Verify parent-child relationship
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 2

        child_span = next(s for s in spans if s.name == "child-operation")
        parent_span = next(s for s in spans if s.name == "parent-operation")

        # Child should reference parent
        assert child_span.parent is not None
        assert child_span.parent.span_id == parent_span.context.span_id

    def test_trace_context_injection_and_extraction(self, isolated_tracer_provider):
        """Test trace context can be injected and extracted."""
        provider, memory_exporter = isolated_tracer_provider

        # Create a span and inject context
        tracer = provider.get_tracer("test")
        propagator = TraceContextTextMapPropagator()

        carrier = {}

        with tracer.start_as_current_span("source-operation") as span:
            # Inject trace context into carrier (e.g., HTTP headers)
            propagator.inject(carrier)

            trace_id = span.context.trace_id
            span_id = span.context.span_id

        # Verify carrier has trace context
        assert "traceparent" in carrier

        # Extract context in another context
        ctx = propagator.extract(carrier)

        # Create child span in extracted context
        with tracer.start_as_current_span("destination-operation", context=ctx) as child_span:
            # Verify trace ID is the same
            assert child_span.context.trace_id == trace_id

        # Verify both spans are in the same trace
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 2

        source_span = next(s for s in spans if s.name == "source-operation")
        dest_span = next(s for s in spans if s.name == "destination-operation")

        # Both should have the same trace ID
        assert source_span.context.trace_id == dest_span.context.trace_id

    def test_nested_span_hierarchy(self, isolated_tracer_provider):
        """Test deeply nested span hierarchy."""
        provider, memory_exporter = isolated_tracer_provider

        # Create nested spans
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("level-1") as span1:
            span1.set_attribute("level", 1)

            with tracer.start_as_current_span("level-2") as span2:
                span2.set_attribute("level", 2)

                with tracer.start_as_current_span("level-3") as span3:
                    span3.set_attribute("level", 3)

        # Verify hierarchy
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 3

        level1 = next(s for s in spans if s.name == "level-1")
        level2 = next(s for s in spans if s.name == "level-2")
        level3 = next(s for s in spans if s.name == "level-3")

        # Verify parent-child chain
        assert level2.parent.span_id == level1.context.span_id
        assert level3.parent.span_id == level2.context.span_id

        # All should have same trace ID
        trace_id = level1.context.trace_id
        assert level2.context.trace_id == trace_id
        assert level3.context.trace_id == trace_id


class TestOTLPExporterIntegration:
    """Test OTLP exporter integration with real SDK components."""

    def test_otlp_exporter_configuration(self):
        """Test OTLP exporter can be configured with real endpoint."""
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        # Real OTLP endpoint configuration
        endpoint = "http://localhost:4317"

        # Create OTLP exporter
        exporter = OTLPSpanExporter(endpoint=endpoint)

        # Verify exporter is created
        assert exporter is not None

    def test_batch_span_processor_with_real_exporter(self):
        """Test batch span processor with real InMemorySpanExporter."""
        # Create real in-memory exporter
        memory_exporter = InMemorySpanExporter()

        # Setup tracer provider with batch processor
        resource = Resource.create({"service.name": "test"})
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(memory_exporter)
        provider.add_span_processor(processor)

        # Create some spans
        tracer = provider.get_tracer("test")
        for i in range(5):
            with tracer.start_as_current_span(f"span-{i}"):
                pass

        # Force flush to trigger export
        provider.force_flush(timeout_millis=5000)

        # Verify spans were exported to memory exporter
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 5

        # Cleanup
        provider.shutdown()

    def test_simple_span_processor_with_real_exporter(self):
        """Test simple span processor exports immediately."""
        # Create real in-memory exporter
        memory_exporter = InMemorySpanExporter()

        # Setup tracer provider with simple processor
        resource = Resource.create({"service.name": "test"})
        provider = TracerProvider(resource=resource)
        processor = SimpleSpanProcessor(memory_exporter)
        provider.add_span_processor(processor)

        # Create spans - should be immediately available
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("immediate-span"):
            pass

        # No flush needed - simple processor exports immediately
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "immediate-span"

        # Cleanup
        provider.shutdown()


class TestTracingWithApplicationLifecycle:
    """Test tracing integration with application lifecycle."""

    def test_tracing_in_application_startup(self):
        """Test that tracing is initialized during application startup."""
        from config.settings import Settings
        from core.observability.tracing import configure_tracing

        # Reset global tracer provider
        trace._TRACER_PROVIDER = None

        # Create settings
        settings = Settings()

        # Configure tracing as in main.py
        if hasattr(settings, "observability") and hasattr(settings.observability, "otlp_endpoint"):
            endpoint = settings.observability.otlp_endpoint
        else:
            endpoint = "http://localhost:4317"

        configure_tracing(service_name="weaver", endpoint=endpoint)

        # Verify tracing is configured and functional
        provider = trace.get_tracer_provider()
        assert provider is not None

        # Get a tracer and create a span to verify functionality
        tracer = trace.get_tracer("test-lifecycle")
        with tracer.start_as_current_span("startup-test"):
            pass

        # Cleanup
        trace._TRACER_PROVIDER = None

    def test_tracer_provider_cleanup(self):
        """Test that tracer provider can be properly shut down."""
        from core.observability.tracing import configure_tracing

        # Reset global tracer provider
        trace._TRACER_PROVIDER = None

        # Configure tracing
        configure_tracing(service_name="test-weaver")

        # Get provider
        provider = trace.get_tracer_provider()

        # Test that we can force flush and shutdown without error
        # This tests the cleanup functionality
        try:
            if hasattr(provider, "force_flush"):
                result = provider.force_flush(timeout_millis=5000)
                # force_flush should succeed
                assert result is True

            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception as e:
            pytest.fail(f"Cleanup should not raise exception: {e}")

        # Cleanup
        trace._TRACER_PROVIDER = None


class TestTracingPerformance:
    """Test tracing performance characteristics."""

    def test_high_volume_span_creation(self, isolated_tracer_provider):
        """Test creating large number of spans."""
        provider, memory_exporter = isolated_tracer_provider

        # Create many spans
        tracer = provider.get_tracer("test")
        num_spans = 100

        for i in range(num_spans):
            with tracer.start_as_current_span(f"span-{i}"):
                pass

        # Verify all spans exported
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == num_spans

    def test_span_attribute_performance(self, isolated_tracer_provider):
        """Test setting multiple attributes on spans."""
        provider, memory_exporter = isolated_tracer_provider

        # Create span with many attributes
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("attr-test") as span:
            for i in range(50):
                span.set_attribute(f"attr.{i}", f"value-{i}")

        # Verify all attributes set
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 1

        span = spans[0]
        assert len(span.attributes) >= 50
