# Security Policy

## Status

Serpentine is **experimental** (readiness level L1; see [docs/readiness.md](docs/readiness.md)).
Its runtime contains hand-written `unsafe` code and parsers for untrusted input: HTTP, JSON,
TOML, URL, regex, DEFLATE/zip and TLS glue. These have **not yet been fuzzed or run under
sanitizers**. Don't expose Serpentine-built services to untrusted networks without your own
review.

## Supported versions

Only the latest release gets fixes:

| Package | Supported |
|---|---|
| `serpentine-lang` latest 0.7.x | ✅ |
| `serpentine-shim` latest | ✅ |
| `serp-*` / `serpentine-*` libraries, latest version of each | ✅ |
| anything older | ❌ |

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub's private
vulnerability reporting: the repository's **Security** tab, then **Report a vulnerability**
(https://github.com/avijitbhuin21/Serpentine/security/advisories/new).

Please include:
- affected package(s) and version(s), OS, and backend (`--backend llvm` or `rust`)
- a minimal reproducer (Serpentine source, input, and the observed crash or behavior)
- the impact as you see it (memory corruption, DoS, TLS validation bypass, ...)

You'll get an acknowledgement as soon as possible. Once the fix has shipped, the advisory will be
published with credit, unless you'd rather stay anonymous.
