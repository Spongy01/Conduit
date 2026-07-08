from opentelemetry.trace import Tracer

from gateway.core.tracer import tracer


def test_tracer_is_a_valid_otel_tracer():
    assert isinstance(tracer, Tracer)


def test_tracer_can_start_a_span():
    with tracer.start_as_current_span("test-span") as span:
        assert span is not None
