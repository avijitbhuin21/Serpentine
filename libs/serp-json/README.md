# serp-json

Serpentine's JSON library ([P] pure Serpentine, docs/libraries.md Wave 1) — the promoted
`examples/json_parser.py` north-star demo.

- `from serp_json import JVal, loads, dumps, describe, jnull, jbool, jint, jfloat, jstr`
- `loads(doc)` parses a JSON document into a `JVal` tree (kind-tagged dataclass);
  `dumps(v)` serializes it back. Object member order is preserved on both sides.
- Escapes (`\uXXXX` incl. surrogate pairs), nested values, and error positions are
  supported; malformed input raises `ValueError` with a position message.
- Integers beyond 64 bits overflow natively (documented int64 divergence).
- Pure Serpentine source: the same file compiles natively and imports under CPython.

Install into a Serpentine project with `serp add serp-json`.
