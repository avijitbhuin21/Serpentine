# serp-re

A `re` drop-in with true backtracking semantics, written in the Serpentine
subset. Patterns compile to a small instruction program run by a recursive
backtracking VM: alternation is first-alternative-wins, quantifiers are
greedy/lazy with full backtracking into repeated bodies, and capture groups
record the last iteration — CPython semantics, verified by 30,000+
differential checks against the real `re` module (including a 3k random
pattern fuzz).

## API

`compile(pattern, flags=0) -> Pattern`, `match`, `fullmatch`, `search`
(returning `Match | None`), `findall`, `finditer` (eager `list[Match]`),
`sub`, `split`, `escape`, the `error` exception (CPython 3.11 messages), and
flags `IGNORECASE/I`, `MULTILINE/M`, `DOTALL/S` (combine with `+` — the
subset has no `|` on ints). `Match` supports `group(n)/groups()/start/end/
span/string` and prints as `<re.Match object; span=(0, 3), match='abc'>`.

## Supported syntax

Literals, `.`, escapes (`\d \D \w \W \s \S \b \B \A \Z`, punctuation,
`\n \t \r \f \v`), classes `[abc]` / `[a-z]` / `[^...]`, quantifiers
`* + ? {m} {m,} {,n} {m,n}` plus lazy variants, groups `(...)`, `(?:...)`,
`(?P<name>...)` (positional access), alternation `|`, anchors `^ $`.

## Caps (loud errors or documented divergences)

- No backreferences or lookarounds (raise `error`).
- `\w`/`\s` classification is ASCII.
- `findall` with 2+ capture groups raises (use `finditer`).
- `groups()` returns a PyVal list, not a tuple; `split()` fills unmatched
  group parts with `''` instead of `None`.
- `sub` replacement is a string template (`\1`, `\g<n>`, escapes) — no
  callables. `finditer` is eager. `{m,n}` capped at 1000.
- The engine recurses while backtracking; very long quantified matches can
  exhaust the stack.

## Install

```
serp add serp-re
pip install serp-re
```
