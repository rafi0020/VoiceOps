"""OpenTelemetry spans for model calls and tool calls.

Attribute names follow the OpenTelemetry GenAI semantic conventions. Those conventions are still marked
"Development" and have been renamed before, so every name is defined once, here.

All spans of a call share one trace, whichever API process produced them: the trace id IS the call id (both are
128-bit), so a call resumed by another process (after a supervisor's decision, or a restart) reads as one trace.
The parameter and attribute keep the name `run` that the shared tracing schema (and AgentOps) uses for one agent
conversation; here it holds the call id.

Nothing is exported unless OTEL_EXPORTER_OTLP_ENDPOINT is set. Prompts, completions and tool arguments are
never put on spans: they can contain business data.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, Status, StatusCode, TraceFlags

from app.config import get_settings

OPERATION = "gen_ai.operation.name"
PROVIDER = "gen_ai.provider.name"
REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
INPUT_TOKENS = "gen_ai.usage.input_tokens"
OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ID = "gen_ai.tool.call.id"
RUN_ID = "voiceops.run.id"
ORG_ID = "voiceops.org.id"
STEP_INDEX = "voiceops.step.index"
COST_USD = "voiceops.cost.usd"

_provider: TracerProvider | None = None


def configure_tracing(exporter: SpanExporter | None = None) -> None:
    """Called once per process. With no exporter given, export only if an OTLP endpoint is configured."""
    global _provider
    _provider = TracerProvider(resource=Resource.create({"service.name": "voiceops-agent"}))
    if exporter is not None:
        _provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif get_settings().otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = get_settings().otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))


def _tracer() -> trace.Tracer:
    if _provider is None:
        configure_tracing()
    return _provider.get_tracer("voiceops.agent")


def _run_context(run_id: UUID):
    parent = SpanContext(
        trace_id=run_id.int, span_id=run_id.int >> 64 or 1, is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED)
    )
    return trace.set_span_in_context(NonRecordingSpan(parent))


@contextmanager
def traced(kind: str, name: str, *, run_id: UUID, org_id: UUID, step: int, **attributes) -> Iterator[trace.Span]:
    """A span around one model call (kind='model') or one tool call (kind='tool')."""
    operation = "chat" if kind == "model" else "execute_tool"
    with _tracer().start_as_current_span(f"{operation} {name}", context=_run_context(run_id)) as span:
        span.set_attribute(OPERATION, operation)
        span.set_attribute(REQUEST_MODEL if kind == "model" else TOOL_NAME, name)
        span.set_attribute(RUN_ID, str(run_id))
        span.set_attribute(ORG_ID, str(org_id))
        span.set_attribute(STEP_INDEX, step)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise
