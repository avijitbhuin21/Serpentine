"""serp-tracing — OpenTelemetry-style distributed tracing for Serpentine services.

`tracer = get_tracer("svc")` and `with tracer.start_as_current_span("name") as span:` give
nested spans with 128-bit trace ids and 64-bit span ids, parent/child links through a
per-thread current-span stack, `span.set_attribute/add_event/set_status`, and W3C Trace
Context propagation: `inject(headers)` writes `traceparent`, `extract(headers)` reads it, and
`start_as_current_span(name, context=extract(headers))` continues a remote trace.

Finished spans are exported as one OTLP-flavoured JSON object per line to the configured
exporter: `"memory"` (default; `finished_spans()` / `clear_spans()`, process-global so worker
threads report together), `"stderr"`, or `"file"` (appends to a path).

Caps: no OTLP/HTTP exporter or sampling (record everything); attribute values are
str/int/float/bool; exceptions inside a `with` block aren't recorded automatically (call
`span.set_status("ERROR", msg)`); `get_current_span()` returns a `SpanContext`, not the live span.
"""
from __future__ import annotations
from serpentine import Mut, PyVal, Ref, dataclass, move
from serp_json import dumps
from serp_log_core import lg_get, lg_set, lg_write_err
from serp_metrics_core import mx_meta_add, mx_meta_get, mx_meta_set
from serp_secrets_core import s_token_hex
from serp_time import time_ns

_STACK_KEY: str = "serp.trace.stack"
_HEX: str = "0123456789abcdef"


@dataclass
class SpanContext:
    trace_id: str
    span_id: str

    @property
    def is_valid(self: Ref[SpanContext]) -> bool:
        return self.trace_id != "" and self.span_id != ""


def _stack() -> list[str]:
    """This thread's open spans, innermost last, as 'trace:span' entries."""
    text: str = lg_get(_STACK_KEY)
    out: list[str] = []
    if text == "":
        return out
    for e in text.split(","):
        out.append(e)
    return out


def _push(trace_id: str, span_id: str) -> None:
    """Make a span the current one on this thread."""
    cur: str = lg_get(_STACK_KEY)
    entry: str = trace_id + ":" + span_id
    lg_set(_STACK_KEY, entry if cur == "" else cur + "," + entry)


def _pop(span_id: str) -> None:
    """Remove a span from this thread's stack (it is normally the innermost)."""
    keep: list[str] = []
    for e in _stack():
        if not e.endswith(":" + span_id):
            keep.append(e)
    lg_set(_STACK_KEY, ",".join(keep))


def get_current_span() -> SpanContext:
    """The innermost open span on this thread (invalid SpanContext when none)."""
    st: list[str] = _stack()
    if len(st) == 0:
        return SpanContext("", "")
    top: str = st[len(st) - 1]
    c: int = top.find(":")
    return SpanContext(top[0:c], top[c + 1:len(top)])


def _is_hex(s: str, n: int) -> bool:
    """True when s is exactly n lowercase hex digits and not all zeros."""
    if len(s) != n:
        return False
    zero: bool = True
    for ch in s:
        if _HEX.find(ch) < 0:
            return False
        if ch != "0":
            zero = False
    return not zero


def extract(carrier: Ref[dict[str, str]]) -> str:
    """The incoming W3C `traceparent` header if it is well formed, else ''."""
    v: str | None = carrier.get("traceparent")
    if v is None:
        return ""
    parts: list[str] = v.strip().lower().split("-")
    if len(parts) != 4 or parts[0] != "00" or not _is_hex(parts[1], 32) \
            or not _is_hex(parts[2], 16) or len(parts[3]) != 2:
        return ""
    return "00-" + parts[1] + "-" + parts[2] + "-" + parts[3]


def inject(carrier: Mut[dict[str, str]]) -> None:
    """Write the current span as a W3C `traceparent` header (no-op outside a span)."""
    ctx: SpanContext = get_current_span()
    if ctx.is_valid:
        carrier["traceparent"] = "00-" + ctx.trace_id + "-" + ctx.span_id + "-01"


def set_exporter(kind: str, path: str = "") -> None:
    """Choose where finished spans go: 'memory' (default), 'stderr' or 'file' (with path)."""
    if kind != "memory" and kind != "stderr" and kind != "file":
        raise ValueError(f"unknown exporter {kind!r}")
    if kind == "file" and path == "":
        raise ValueError("the file exporter needs a path")
    mx_meta_set("serp.trace.exporter", kind)
    mx_meta_set("serp.trace.path", path)


def finished_spans() -> list[str]:
    """JSON lines of every span exported to memory so far, in end order."""
    text: str = mx_meta_get("serp.trace.spans")
    out: list[str] = []
    if text == "":
        return out
    for line in text[1:len(text)].split("\n"):
        out.append(line)
    return out


def clear_spans() -> None:
    """Forget the in-memory spans."""
    mx_meta_set("serp.trace.spans", "")


def _export(line: str) -> None:
    """Send one finished span to the configured exporter."""
    kind: str = mx_meta_get("serp.trace.exporter")
    if kind == "stderr":
        lg_write_err(line)
    elif kind == "file":
        with open(mx_meta_get("serp.trace.path"), "a") as f:
            f.write(line + "\n")
    else:
        added: bool = mx_meta_add("serp.trace.spans", line)


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str
    start_time: int
    kind: str = "INTERNAL"
    attributes: dict[str, PyVal] = {}
    events: list[str] = []
    status: str = "UNSET"
    status_description: str = ""
    end_time: int = 0

    def __enter__(self: Ref[Span]) -> Span:
        return self

    def __exit__(self: Mut[Span], exc_type: None, exc: None, tb: None) -> None:
        self.end()

    def set_attribute(self: Mut[Span], key: str, value: PyVal) -> None:
        self.attributes[key] = value

    def add_event(self: Mut[Span], name: str) -> None:
        self.events.append(name)

    def set_status(self: Mut[Span], status: str, description: str = "") -> None:
        """'OK', 'ERROR' or 'UNSET' (OpenTelemetry StatusCode names)."""
        if status != "OK" and status != "ERROR" and status != "UNSET":
            raise ValueError(f"invalid status {status!r}")
        self.status = status
        self.status_description = description

    def get_span_context(self: Ref[Span]) -> SpanContext:
        return SpanContext(self.trace_id, self.span_id)

    def is_recording(self: Ref[Span]) -> bool:
        return self.end_time == 0

    def end(self: Mut[Span]) -> None:
        """Finish the span once: pop it from the context and export it."""
        if self.end_time != 0:
            return
        self.end_time = time_ns()
        _pop(self.span_id)
        attrs: dict[str, PyVal] = {}
        for k, v in self.attributes.items():
            attrs[k] = v
        evs: list[PyVal] = []
        for e in self.events:
            evs.append(e)
        a: PyVal = move(attrs)
        ev: PyVal = move(evs)
        doc: PyVal = {"name": self.name, "trace_id": self.trace_id, "span_id": self.span_id,
                      "parent_span_id": self.parent_span_id, "kind": self.kind,
                      "start_time_unix_nano": self.start_time,
                      "end_time_unix_nano": self.end_time, "attributes": a, "events": ev,
                      "status": self.status, "status_description": self.status_description}
        _export(dumps(doc, compact=True))


@dataclass
class Tracer:
    instrumentation_name: str

    def start_as_current_span(self: Ref[Tracer], name: str, context: str = "",
                              kind: str = "INTERNAL") -> Span:
        """Open a span as a child of `context` (a traceparent) or of the current span."""
        trace_id: str = ""
        parent: str = ""
        if context != "":
            parts: list[str] = context.split("-")
            trace_id = parts[1]
            parent = parts[2]
        else:
            cur: SpanContext = get_current_span()
            if cur.is_valid:
                trace_id = cur.trace_id
                parent = cur.span_id
        if trace_id == "":
            trace_id = s_token_hex(16)
        span_id: str = s_token_hex(8)
        _push(trace_id, span_id)
        sp: Span = Span(name, trace_id, span_id, parent, time_ns(), kind)
        sp.attributes["otel.scope.name"] = self.instrumentation_name
        return sp


def get_tracer(instrumenting_module_name: str) -> Tracer:
    """A tracer stamped with the instrumentation scope name."""
    return Tracer(instrumenting_module_name)
