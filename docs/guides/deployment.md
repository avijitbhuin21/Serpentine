# Deploying a Venom service

How to run a Serpentine web service (Venom) in production: health checks, graceful
shutdown, timeouts, process managers and containers. Everything here is exercised by
`tools/run_shutdown_check.py` and `libs/serp-venom/tests/test_shutdown.py`.

## 1. Build one static-ish binary

```bash
serp build app.py -o app            # Backend A (rustc), release by default
serp build app.py -o app --backend llvm
```

The output is a single native executable. Its only runtime dependencies are the OS TLS
stack (schannel on Windows, the system OpenSSL on Linux/macOS) and, when you use
`serp-sqlite`, the system SQLite. There's no interpreter or virtualenv on the server.

## 2. Health endpoint

Expose a cheap route that doesn't touch dependencies (liveness) and, if needed, one that does
(readiness):

```python
from serp_fastapi import FastAPI

app = FastAPI()

@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/readyz")
def readyz() -> dict[str, str]:
    # check the database / downstream services here; raise HTTPException(503) when not ready
    return {"status": "ready"}
```

Point the load balancer, Kubernetes probes or Docker `HEALTHCHECK` at these paths.

## 3. Graceful shutdown

`serp_fastapi.run(app, host, port)` installs the signal handler for you. With your own serve
loop, call `shutdown_install()` once before serving:

| Signal | Effect |
|---|---|
| first SIGTERM / SIGINT (Ctrl-C), or Ctrl-Break / console close on Windows | stop accepting; finish requests already in flight; close idle keep-alive connections; the serve loop returns |
| second signal | terminate immediately |

- `serve_async` (the event loop that `run` uses) drains for up to `SHUTDOWN_GRACE` (10 s),
  then closes whatever is left.
- `serve_on` workers (thread per worker) finish their current request, close the connection
  and return. Join the workers in `main` and the process exits 0.
- `shutdown_request()` triggers the same drain from code (admin endpoint, tests);
  `shutdown_requested()` reports it.
- The asyncio path (`accept_async` + `serve_conn`) doesn't poll the flag yet. Bound it with
  your own loop condition.

Set your orchestrator's stop timeout above the grace period (for example
`terminationGracePeriodSeconds: 15`, `docker stop -t 15`, systemd `TimeoutStopSec=15`).

## 4. Timeouts and limits (built in)

| Limit | Value | Where |
|---|---|---|
| Per-`recv` idle timeout | 10 s | every accepted connection |
| Whole-request read deadline (slowloris) | 30 s (`REQUEST_DEADLINE`) | head + body must arrive within it; `serve_async(..., read_deadline=)` overrides |
| Request head | 64 KiB | larger heads are dropped |
| Request body | 16 MiB (`MAX_BODY`) | larger declared bodies get 413 |

Still put a reverse proxy (nginx, Caddy, a cloud load balancer) in front for TLS
termination, HTTP/2 and request buffering. Venom serves HTTP/1.1 only.

## 5. systemd

```ini
[Unit]
Description=my-service
After=network-online.target

[Service]
ExecStart=/opt/my-service/app
Restart=on-failure
RestartSec=2
KillSignal=SIGTERM
TimeoutStopSec=15
User=my-service
Environment=PORT=8000

[Install]
WantedBy=multi-user.target
```

## 6. Docker

```dockerfile
FROM python:3.12-slim AS build
RUN pip install serpentine-lang && apt-get update && apt-get install -y --no-install-recommends gcc curl \
    && curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH=/root/.cargo/bin:$PATH
WORKDIR /src
COPY . .
RUN serp build app.py -o /out/app

FROM debian:stable-slim
RUN apt-get update && apt-get install -y --no-install-recommends libssl3 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/app /app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=2s CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
STOPSIGNAL SIGTERM
ENTRYPOINT ["/app"]
```

The binary must listen on `0.0.0.0` inside a container. Install `libsqlite3-0` too if you
use `serp-sqlite`. Run the binary as PID 1 directly (exec-form `ENTRYPOINT`) so it receives
SIGTERM.

## 7. Kubernetes probes

```yaml
livenessProbe:
  httpGet: { path: /healthz, port: 8000 }
  periodSeconds: 10
readinessProbe:
  httpGet: { path: /readyz, port: 8000 }
  periodSeconds: 5
terminationGracePeriodSeconds: 15
```

## 8. Scaling

One `serve_async` loop is single-threaded. For more cores, either run N processes behind the
load balancer, or bind once and start N `serve_on` / `serve_async` workers on the shared
listening fd (`listen()` returns a fd that worker threads may share; see `tools/soak/app.py`).
