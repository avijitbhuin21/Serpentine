# Serpentine Documentation

> One folder for everything. Start with [features.md](features.md) for what works today;
> [spec.md](spec.md) is the spec-of-record.

## Core

| Doc | What |
|---|---|
| [spec.md](spec.md) | **Spec-of-record** for the compilable subset (Tier 0–2). Changes are spec changes. |
| [features.md](features.md) | Current feature state — language, compiler, tooling, libraries. |
| [decisions.md](decisions.md) | Resolved design decisions (D1–D9+). Reopening one is a spec change. |
| [libraries.md](libraries.md) | Library roadmap & tracker — every `serp-*` dist, wave by wave. |

## Language

| Doc | What |
|---|---|
| [language/tour.md](language/tour.md) | Guided tour of the language. |
| [language/ownership.md](language/ownership.md) | The ownership & borrowing model. |
| [language/exceptions-ownership.md](language/exceptions-ownership.md) | Paper prototype: exceptions × ownership. |
| [language/divergences.md](language/divergences.md) | Documented CPython-vs-native divergences. |
| [language/python-equivalence.md](language/python-equivalence.md) | Per-library stdlib drop-in status & blockers. |

## Guides

| Doc | What |
|---|---|
| [guides/migration.md](guides/migration.md) | Migrating Python code to Serpentine. |
| [guides/interop.md](guides/interop.md) | Foreign-import (interop) policy. |
| [guides/packages.md](guides/packages.md) | Packages, `serp.toml`, dependency resolution. |
| [guides/publishing.md](guides/publishing.md) | Publishing libraries & releases. |
| [guides/benchmarks.md](guides/benchmarks.md) | Benchmark methodology & results. |

## Archive (historical)

| Doc | What |
|---|---|
| [archive/research.md](archive/research.md) | The research & design document that seeded the project. |
| [archive/checklist.md](archive/checklist.md) | The phase-by-phase execution tracker (Phases 0–7). |
| [archive/corpus-study.md](archive/corpus-study.md) | Tier-2 feature-demand corpus study. |
