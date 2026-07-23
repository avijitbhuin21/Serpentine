# serpentine-lang

The Serpentine compiler (`serp` CLI). Phase-1 walking skeleton:

- `serp check entry.py` — frontend, type checker, SIR ownership analyses; exits 0/1.
- `serp build entry.py [-o out] [--keep-rust]` — Backend A: transpiles to Rust and invokes
  `rustc` to produce a native binary with no libpython dependency.

The Tier-0 language is specified in the repository's `docs/spec.md`; the test corpus under
`tests/` is the executable half of that spec.
