# serp-strings

Textwrap-style string helpers written in the Serpentine subset: the same
source compiles to native code with `serp` and imports under CPython.

## API

- `wrap(text, width) -> list[str]` / `fill(text, width) -> str` — greedy
  whitespace-collapsing word wrap; words longer than `width` are hard-broken.
- `indent(text, prefix)` — prefix every non-blank line.
- `dedent(text)` — remove the common leading whitespace of non-blank lines.
- `ljust / rjust / center (s, width, fill=" ")` — padding helpers
  (`center` puts the extra pad character on the right).
- `expandtabs(s, tabsize=8)` — column-aware tab expansion.
- `repeat_char(ch, n)` — building block, exported for convenience.

## Install

```
serp add serp-strings   # native projects
pip install serp-strings  # CPython
```
