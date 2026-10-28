"""OpenTelemetry tracing. Enabled when OTEL_EXPORTER_OTLP_ENDPOINT is set; a no-op otherwise.

Span attributes carry identifiers, strategies, and costs only, never prompts, outputs, or keys.
"""

import os
from contextlib import contextmanager

from opentelemetry import trace

tracer = trace.get_tracer("omniweb.aaee")


def setup(app) -> None:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "omniweb-ai-execution-engine"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")


@contextmanager
def span(name: str, **attributes):
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(f"aaee.{key}", value if isinstance(value, str | int | float | bool) else str(value))
        yield current
