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
| [readiness.md](readiness.md) | Production-readiness checklist — P0/P1/P2 items across CI, releases, security, ops, ecosystem. |

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

