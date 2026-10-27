# Stability & versioning policy

What you can rely on across Serpentine releases, and how changes are announced. Applies to
`serpentine-lang` (compiler + `serp` CLI), `serpentine-shim`, the native runtime, and the
`serp-*` libraries.

## Version numbers

Everything follows [Semantic Versioning](https://semver.org/) with the standard pre-1.0 rule:
while a package is `0.x`, the **minor** number is the breaking-change number.

| Bump | `0.x` packages (today) | `≥1.0` packages |
|---|---|---|
| patch `0.7.2 → 0.7.3` | bug fixes, new diagnostics for programs that already failed, performance, docs | same |
| minor `0.7 → 0.8` | may break source, CLI flags, `serp.toml` keys, the runtime ABI or SE codes (each break listed in CHANGELOG under **Breaking**) | new features only, backwards compatible |
| major | n/a | breaking changes |

Pin with a compatible-release specifier on the minor: `serpentine-lang~=0.7.2` (so
`>=0.7.2,<0.8`), and `serp.lock` pins exact library versions.

## Surfaces and their guarantees

| Surface | Guarantee within one minor series (`0.7.*`) |
|---|---|
| **Accepted programs** | A program that `serp check` accepts and that runs identically under CPython and native keeps doing so. Fixing a miscompile counts as a bug fix even when output changes, because the CPython output is the contract (SPEC 1.1). |
| **Rejected programs** | May become accepted (features land in patches). New rejections land only when the program was already miscompiled or unsound, and are listed in CHANGELOG. |
| **SE error codes** | A code never changes meaning. New codes may appear; retired codes are never reused. Message wording may change; match on the code. |
| **Spec & decisions** | `docs/spec.md` and `docs/DECISIONS.md` (D1–D45) change only through a recorded decision; reopening one is a minor-version event. |
| **CLI** (`serp build/check/run/test/init/new/add/remove`) | Existing commands and flags keep working; new flags may be added. |
| **`serp.toml` / `serp.lock`** | Existing keys keep their meaning; unknown keys are rejected so typos surface. |
| **Runtime ABI** (`prelude.rs`/`rt.rs`, prebuilt `serp-rt-<ver>-<platform>.zip`) | Internal. Binaries are self-contained, and the runtime is rebuilt or downloaded per compiler version (keyed by a hash of the runtime source), so there is no cross-version ABI to keep. Never link objects from two compiler versions. |
| **`serpentine-shim`** | Additive within a major line. Every name the compiler recognizes stays importable. |
| **`serp-*` libraries** | Versioned independently. Drop-in libraries track their CPython counterpart's API; a divergence fix that changes output is a minor bump for that library. |

## Deprecation

1. The replacement ships first; the old form keeps working and gets a warning (or a
   CHANGELOG **Deprecated** entry where no warning channel exists).
2. Removal happens no earlier than the next minor (pre-1.0) or major (post-1.0) release.

## Supported versions

Security fixes go to the latest minor of `serpentine-lang` and the latest release of each
`serp-*` library (see [SECURITY.md](../SECURITY.md)). Older minors aren't patched.

## Road to 1.0

`1.0` freezes the Tier 0–2 language surface, the SE code table and the CLI under the `≥1.0`
column above. Its prerequisites are the L3 items in [readiness.md](readiness.md).
