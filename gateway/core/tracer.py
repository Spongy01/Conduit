"""Shared OTel tracer for every manual span in the gateway. Call sites
import `tracer` from here rather than calling `trace.get_tracer(...)`
themselves, so all manual spans share one instrumentation scope name."""
from opentelemetry import trace

tracer = trace.get_tracer("conduit.gateway")
