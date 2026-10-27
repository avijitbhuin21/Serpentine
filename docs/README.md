# Serpentine Documentation

> One folder for everything. Start with [features.md](features.md) for what works today;
> [spec.md](spec.md) is the spec-of-record.

## Core

| Doc | What |
|---|---|
| [spec.md](spec.md) | **Spec-of-record** for the compilable subset (Tier 0–2). Changes are spec changes. |
| [features.md](features.md) | Current feature state — language, compiler, tooling, libraries. |
| [DECISIONS.md](DECISIONS.md) | Resolved design decisions (D1–D12+). Reopening one is a spec change. |
| [libraries.md](libraries.md) | Library tracker — every `serp-*` dist, wave by wave, one line each, blockers at the bottom. |
| [readiness.md](readiness.md) | Production-readiness checklist — verdict (L1/L2/L3), remaining work by priority, done items with evidence. |
| [stability.md](stability.md) | Stability & versioning policy — SemVer rules, per-surface guarantees, deprecation. |
| [../CHANGELOG.md](../CHANGELOG.md) | What shipped in each compiler/shim release. |
| [../SECURITY.md](../SECURITY.md) | Vulnerability reporting and supported versions. |

## Language

| Doc | What |
|---|---|
| [language/tour.md](language/tour.md) | Guided tour of the language. |
| [language/ownership.md](language/ownership.md) | The ownership & borrowing model. |
| [language/divergences.md](language/divergences.md) | Documented CPython-vs-native divergences. |

## Libraries

| Doc | What |
|---|---|
| [libraries.md](libraries.md) | Tracker — one line per `serp-*` dist. |
| [libraries/venom.md](libraries/venom.md) | **Venom** roadmap — path to axum-class perf and drop-in `fastapi`. |
| [libraries/molt.md](libraries/molt.md) | **Molt** roadmap — `pydantic` v2 drop-in, language blockers (LB*). |
| [libraries/scales.md](libraries/scales.md) | **Scales** roadmap — `pandas` surface and typed storage. |

`libraries/<name>.md` holds the working checklist for a library that has one; the tracker
stays one line per library.

## Guides

| Doc | What |
|---|---|
| [guides/migration.md](guides/migration.md) | Migrating Python code to Serpentine. |
| [guides/interop.md](guides/interop.md) | Foreign-import (interop) policy. |
| [guides/packages.md](guides/packages.md) | Packages, `serp.toml`, dependency resolution. |
| [guides/publishing.md](guides/publishing.md) | Publishing libraries & releases. |
| [guides/benchmarks.md](guides/benchmarks.md) | Benchmark methodology & results. |
| [guides/testing.md](guides/testing.md) | Test suites, fuzzers, Miri/ASan, traceback/TLS checks and the soak test. |
| [guides/deployment.md](guides/deployment.md) | Running a Venom service: health endpoints, graceful shutdown, timeouts, systemd/Docker/Kubernetes. |

