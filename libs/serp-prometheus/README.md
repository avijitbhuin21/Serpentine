# serp-prometheus

Prometheus metrics for [Serpentine](https://github.com/avijitbhuin21/Serpentine) services, in
`prometheus_client` style.

```python
from serp_fastapi import FastAPI, PlainTextResponse, Response
from serp_prometheus import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUESTS = Counter("http_requests_total", "Total HTTP requests.", ["method", "status"])
LATENCY = Histogram("request_seconds", "Request latency.")

app = FastAPI()

@app.get("/metrics")
def metrics() -> Response:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
```

Values live in a process-global runtime store, so module-level metrics work and every worker
thread reports into the same registry. Output is the Prometheus text format 0.0.4.

Caps: one global registry; no `*_created` samples or process collectors; `labels()` takes up
to four positional values.
