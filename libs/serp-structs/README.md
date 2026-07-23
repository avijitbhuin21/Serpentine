# serp-structs

Data-structure helpers written in the Serpentine subset.

## API

- **Min-heap on `list[int]`**: `heap_push(h, v)`, `heap_pop(h)` (raises
  `IndexError` when empty), `heapify(h)`.
- **Bisect on sorted `list[int]`**: `bisect_left(xs, v)`, `bisect_right(xs, v)`,
  `insort(xs, v)`.
- **`Deque[T]`** — generic two-stack deque (`Deque([], [])` to construct):
  `push_left/push_right(move(v))`, `pop_left/pop_right()` (raise `IndexError`
  when empty), `size()`, `is_empty()`.
- **Counter helpers**: `count_items(list[str]) -> dict[str, int]`,
  `increment(d, key, by=1)`, `most_common(d, n)` — `(key, count)` tuples,
  count descending, ties by key ascending; `n < 0` returns all.

Heap and bisect are int-first per the roadmap (generic comparisons need
protocol-bounded ordering, which the language does not have yet).

## Install

```
serp add serp-structs
pip install serp-structs
```
