# serp-tracing

OpenTelemetry-style tracing for [Serpentine](https://github.com/avijitbhuin21/Serpentine) services.

```python
from serp_tracing import get_tracer, inject, extract

tracer = get_tracer("checkout")

def handle(headers: dict[str, str]) -> None:
    with tracer.start_as_current_span("request", context=extract(headers), kind="SERVER") as span:
        span.set_attribute("http.route", "/items/{id}")
        downstream: dict[str, str] = {}
        inject(downstream)          # traceparent for the next hop
```

Nested spans link to their parents via a per-thread current-span stack; W3C `traceparent` is
injected and extracted for cross-service traces. Finished spans are written as JSON lines to the
in-memory store (`finished_spans()`), stderr, or a file (`set_exporter("file", path)`).

Caps: no OTLP exporter or sampling; exceptions are not recorded automatically.
