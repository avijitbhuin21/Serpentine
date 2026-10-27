from __future__ import annotations

from serpentine import PyVal, Ref
from serp_json import loads
from serp_tracing import (SpanContext, Tracer, clear_spans, extract, finished_spans,
                          get_current_span, get_tracer, inject, set_exporter)


def is_lower_hex(s: str, n: int) -> bool:
    """True when s is exactly n lowercase hex digits."""
    if len(s) != n:
        return False
    for ch in s:
        if "0123456789abcdef".find(ch) < 0:
            return False
    return True


def fake_handler(tracer: Ref[Tracer], incoming: Ref[dict[str, str]]) -> dict[str, str]:
    """Continue a remote trace and propagate it to a downstream call."""
    out: dict[str, str] = {}
    with tracer.start_as_current_span("server", context=extract(incoming), kind="SERVER") as sp:
        sp.set_attribute("http.route", "/items/{id}")
        inject(out)
    return out


def main() -> None:
    tracer = get_tracer("checkout")
    print("outside:", get_current_span().is_valid)
    with tracer.start_as_current_span("request") as root:
        root.set_attribute("http.method", "GET")
        root.set_attribute("http.status_code", 200)
        root.set_attribute("cache.hit", False)
        ctx: SpanContext = get_current_span()
        print("root current:", ctx.span_id == root.span_id, len(ctx.trace_id), len(ctx.span_id))
        with tracer.start_as_current_span("db.query") as child:
            child.set_attribute("db.rows", 3.5)
            child.add_event("connected")
            child.set_status("OK")
            print("same trace:", child.trace_id == root.trace_id,
                  "parent ok:", child.parent_span_id == root.span_id)
        with tracer.start_as_current_span("render") as second:
            second.set_status("ERROR", "template missing")
        print("back to root:", get_current_span().span_id == root.span_id)
    print("after:", get_current_span().is_valid)

    spans: list[str] = finished_spans()
    print("exported:", len(spans))
    names: list[str] = []
    for line in spans:
        doc: PyVal = loads(line)
        names.append(str(doc["name"]))
        print(doc["name"], doc["kind"], doc["status"], doc["attributes"], doc["events"],
              int(doc["end_time_unix_nano"]) >= int(doc["start_time_unix_nano"]),
              is_lower_hex(str(doc["span_id"]), 16), doc["parent_span_id"] == "")
    print(names)

    remote: dict[str, str] = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    down: dict[str, str] = fake_handler(tracer, remote)
    tp: str = down["traceparent"]
    print("continued:", tp.startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-"), len(tp))
    last: PyVal = loads(finished_spans()[3])
    print("remote parent:", last["parent_span_id"], last["kind"])
    for bad in ["00-xyz-00f067aa0ba902b7-01", "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "00-00000000000000000000000000000000-00f067aa0ba902b7-01"]:
        print("extract bad:", extract({"traceparent": bad}) == "")
    empty: dict[str, str] = {}
    inject(empty)
    print("inject outside span:", len(empty))
    clear_spans()
    print("cleared:", len(finished_spans()))
    try:
        set_exporter("kafka")
    except ValueError as e:
        print("caught:", e)


if __name__ == "__main__":
    main()
