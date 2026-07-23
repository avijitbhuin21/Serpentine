# serp-pathlib

Path helpers written in the Serpentine subset. The string operations are
pure ([P]) and accept both `/` and `\` separators plus Windows drive
prefixes; joins are emitted with `/`. Filesystem queries delegate to
`serp-os` runtime primitives.

## API

- `join(a, b)`, `parent(p)`, `name(p)`, `suffix(p)`, `stem(p)`,
  `with_suffix(p, ".new")`, `parts(p)`, `is_absolute(p)` — pure string ops,
  CPython-pathlib-like semantics for the common cases.
- `exists / is_file / is_dir (p)`, `mkdir / rmdir / remove (p)`,
  `listdir(p)` — re-exported serp-os syscalls (listdir sorted).

## Install

```
serp add serp-pathlib
pip install serp-pathlib
```
