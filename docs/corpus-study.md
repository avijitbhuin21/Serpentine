# Corpus Study — Real Small Programs vs the Tier-0/1 Checker

> Phase-2 step 9 (RESEARCH.md §5.9): run the checker over ordinary small Python programs
> and catalog which idioms the subset rejects. This data drives Tier-2 priorities.

## Method

Four small programs written the way a Python programmer would naturally write them
(no ownership annotations beyond what the subset requires), checked with `serp check`
(Phase-2 checker, 2026-07-17). Program sources are reproduced inline; they are not part
of the test corpus.

## Results

| program | verdict | notes |
|---|---|---|
| Euler 1 (sum of multiples, `range` + accumulator) | **clean** | pure Copy-type arithmetic — zero friction |
| word count (`str.split`, dict get/set, `items()` loop) | **clean** | `if w in counts: counts[w] += 1` idiom passes as-is |
| grade book (dataclasses + `list[Student]`, methods, f-strings) | **clean** | needs `self: Ref[...]` / `Mut[...]` annotations and `Student(...)` ctor moves only for non-Copy args |
| idioms probe (aliasing, element borrow, `sorted`, comprehension) | **4 rejections** | see below |

## Cataloged rejections (Tier-2 demand data)

1. **Aliasing** — `b = a; b.append(4); print(a)` → `SE003 implicit-transfer`.
   Deliberate: this is the core ownership rule. The fix (`move` or borrow) is local.
   *No Tier-2 action; this is the language.*
2. **Element borrow into a named local** — `first: list[int] = rows[0]` → `SE006`.
   Idiomatic Python reads an element into a name and keeps using the container.
   Workarounds exist (index in place, `pop`), but a **scoped element borrow**
   (`with rows[0] as first:` or Tier-2 named borrows) is the single most-wanted
   ergonomic improvement.
3. **`sorted()`** — rejected (`SE201`): builtin returns a new list; needs closures for
   `key=` in general, but a keyless `sorted(xs)` is implementable in Tier 1.5 without
   closures. *Cheap win; queue for Tier 2.*
4. **List comprehensions** — `SE201`. Highest-frequency rejected syntax in real code by
   far. Desugars to a loop + append with no ownership novelty. *Top Tier-2 priority.*

## Conclusions

- Numeric/scripting code and dict/str-processing code pass essentially unchanged.
- Dataclass-based code needs only the self-convention annotations.
- The friction is concentrated in (a) comprehensions, (b) named element borrows,
  (c) tiny builtin gaps (`sorted`). None require ownership-model changes.
