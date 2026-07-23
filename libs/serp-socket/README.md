# serp-socket

TCP and UDP sockets for Serpentine. Runtime-backed ([R]): native builds use
`std::net` in the Serpentine runtime; under CPython the same imports delegate
to the stdlib `socket` module. Handles are opaque ints.

```python
from serp_socket import connect, send, recv, close

h: int = connect("127.0.0.1", 8080, 3000)   # 3s connect timeout
send(h, b"ping")
print(recv(h, 4096))
close(h)
```

## API

TCP:
- `connect(host, port, timeout_ms) -> int` — `timeout_ms > 0` bounds the connect
- `listen(host, port) -> int` (port 0 = pick a free port), `accept(listener) -> int`
- `send(h, data: bytes) -> int` (sends everything), `recv(h, maxlen) -> bytes` (empty = peer closed)
- `shutdown_write(h)` — half-close so the peer sees EOF

UDP:
- `udp_bind(host, port) -> int`, `udp_send_to(h, data, host, port) -> int`
- `udp_recv_from(h, maxlen) -> bytes` + `udp_peer_host(h)` / `udp_peer_port(h)` for the sender

Both:
- `set_timeout(h, ms)` (0 = blocking), `local_port(h) -> int`, `close(h)`

## Errors

Normalized identically in both worlds: `OSError` with one of
`"connection refused"`, `"timed out"`, `"connection reset"`,
`"address in use"`, `"not connected"`, `"address resolution failed"`,
`"socket error"`; misuse raises `ValueError`. IPv4 and IPv6 addresses both
work; hostname resolution takes the first result, so prefer explicit IPs
(`127.0.0.1`) when the family matters.
