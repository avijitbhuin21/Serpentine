# serp-redis

A redis-py-style Redis client (RESP2) for [Serpentine](https://github.com/avijitbhuin21/Serpentine).

```python
from serp_redis import Redis

r = Redis("localhost", 6379, decode_responses=True)
r.set("greeting", "hello", ex=60)
print(r.get("greeting"))          # 'hello'
print(r.incr("hits"))             # 1
r.hset("user:1", "name", "Ada")
print(r.hgetall("user:1"))        # {'name': 'Ada'}
```

Covers strings, counters, expiry, hashes, lists, sets, `publish`, `AUTH`/`SELECT` on connect and a raw
`execute_command([...])`. Server errors raise `ResponseError`; socket failures raise `ConnectionError`.

Caps: one connection per client (no pool), no pipelines/transactions/subscribe/TLS; multi-key commands
take a list; `hgetall` field names are always `str`.
