"""serp-structs — heapq/bisect drop-in names plus deque/Counter-style helpers.

Pure Serpentine ([P]). heappush/heappop/heapify/heappushpop/heapreplace and
bisect_left/bisect_right/bisect/insort_left/insort_right/insort mirror the
CPython stdlib (same algorithms, so heap layouts and error messages match),
capped to list[int] until protocol-bounded generic ordering exists.
Deque[T] is a generic two-stack deque with O(1) amortized ends; counter
helpers build dict[str, int] tallies.
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, TypeVar, Generic, dataclass, move

T = TypeVar("T")


def _siftdown(heap: Mut[list[int]], startpos: int, pos: int) -> None:
    """Bubble the item at pos toward the root, like heapq._siftdown."""
    newitem: int = heap[pos]
    p: int = pos
    while p > startpos:
        parentpos: int = (p - 1) // 2
        parent: int = heap[parentpos]
        if newitem < parent:
            heap[p] = parent
            p = parentpos
        else:
            break
    heap[p] = newitem


def _siftup(heap: Mut[list[int]], pos: int) -> None:
    """Move a root item down to a leaf then bubble it up, like heapq._siftup."""
    endpos: int = len(heap)
    startpos: int = pos
    newitem: int = heap[pos]
    p: int = pos
    childpos: int = 2 * p + 1
    while childpos < endpos:
        rightpos: int = childpos + 1
        if rightpos < endpos and not (heap[childpos] < heap[rightpos]):
            childpos = rightpos
        heap[p] = heap[childpos]
        p = childpos
        childpos = 2 * p + 1
    heap[p] = newitem
    _siftdown(heap, startpos, p)


def heappush(heap: Mut[list[int]], item: int) -> None:
    """Push item onto the heap, maintaining the heap invariant (heapq.heappush)."""
    heap.append(item)
    _siftdown(heap, 0, len(heap) - 1)


def heappop(heap: Mut[list[int]]) -> int:
    """Pop and return the smallest item from the heap (heapq.heappop)."""
    if len(heap) == 0:
        raise IndexError("index out of range")
    lastelt: int = heap.pop()
    if len(heap) > 0:
        returnitem: int = heap[0]
        heap[0] = lastelt
        _siftup(heap, 0)
        return returnitem
    return lastelt


def heapreplace(heap: Mut[list[int]], item: int) -> int:
    """Pop the smallest item and push item in one operation (heapq.heapreplace)."""
    if len(heap) == 0:
        raise IndexError("index out of range")
    returnitem: int = heap[0]
    heap[0] = item
    _siftup(heap, 0)
    return returnitem


def heappushpop(heap: Mut[list[int]], item: int) -> int:
    """Push item then pop the smallest, faster than separate calls (heapq.heappushpop)."""
    if len(heap) > 0 and heap[0] < item:
        old: int = heap[0]
        heap[0] = item
        _siftup(heap, 0)
        return old
    return item


def heapify(x: Mut[list[int]]) -> None:
    """Transform a list into a heap in-place (heapq.heapify)."""
    i: int = len(x) // 2 - 1
    while i >= 0:
        _siftup(x, i)
        i -= 1


def bisect_left(a: Ref[list[int]], x: int, lo: int = 0, hi: int | None = None) -> int:
    """Locate the leftmost insertion point for x in sorted a (bisect.bisect_left)."""
    if lo < 0:
        raise ValueError("lo must be non-negative")
    lo2: int = lo
    hi2: int = len(a)
    if hi is not None:
        hi2 = hi
    while lo2 < hi2:
        mid: int = (lo2 + hi2) // 2
        if a[mid] < x:
            lo2 = mid + 1
        else:
            hi2 = mid
    return lo2


def bisect_right(a: Ref[list[int]], x: int, lo: int = 0, hi: int | None = None) -> int:
    """Locate the rightmost insertion point for x in sorted a (bisect.bisect_right)."""
    if lo < 0:
        raise ValueError("lo must be non-negative")
    lo2: int = lo
    hi2: int = len(a)
    if hi is not None:
        hi2 = hi
    while lo2 < hi2:
        mid: int = (lo2 + hi2) // 2
        if x < a[mid]:
            hi2 = mid
        else:
            lo2 = mid + 1
    return lo2


def bisect(a: Ref[list[int]], x: int, lo: int = 0, hi: int | None = None) -> int:
    """Alias of bisect_right (bisect.bisect)."""
    return bisect_right(a, x, lo, hi)


def insort_left(a: Mut[list[int]], x: int, lo: int = 0, hi: int | None = None) -> None:
    """Insert x into sorted a, before equal entries (bisect.insort_left)."""
    idx: int = bisect_left(a, x, lo, hi)
    a.insert(idx, x)


def insort_right(a: Mut[list[int]], x: int, lo: int = 0, hi: int | None = None) -> None:
    """Insert x into sorted a, after equal entries (bisect.insort_right)."""
    idx: int = bisect_right(a, x, lo, hi)
    a.insert(idx, x)


def insort(a: Mut[list[int]], x: int, lo: int = 0, hi: int | None = None) -> None:
    """Alias of insort_right (bisect.insort)."""
    idx: int = bisect_right(a, x, lo, hi)
    a.insert(idx, x)


@dataclass
class Deque(Generic[T]):
    front: list[T]
    back: list[T]

    def size(self: Ref[Deque[T]]) -> int:
        return len(self.front) + len(self.back)

    def is_empty(self: Ref[Deque[T]]) -> bool:
        return len(self.front) == 0 and len(self.back) == 0

    def push_left(self: Mut[Deque[T]], v: Owned[T]) -> None:
        self.front.append(move(v))

    def push_right(self: Mut[Deque[T]], v: Owned[T]) -> None:
        self.back.append(move(v))

    def pop_left(self: Mut[Deque[T]]) -> T:
        if len(self.front) == 0:
            if len(self.back) == 0:
                raise IndexError("pop from an empty deque")
            while len(self.back) > 0:
                self.front.append(self.back.pop())
        return self.front.pop()

    def pop_right(self: Mut[Deque[T]]) -> T:
        if len(self.back) == 0:
            if len(self.front) == 0:
                raise IndexError("pop from an empty deque")
            while len(self.front) > 0:
                self.back.append(self.front.pop())
        return self.back.pop()


def count_items(xs: Ref[list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for x in xs:
        if x in counts:
            counts[x] += 1
        else:
            counts[x] = 1
    return counts


def increment(d: Mut[dict[str, int]], k: str, by: int = 1) -> None:
    if k in d:
        d[k] += by
    else:
        d[k] = by


def most_common(counts: Ref[dict[str, int]], n: int) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    for k, v in counts.items():
        entry: tuple[str, int] = (k, v)
        inserted: bool = False
        for i in range(len(entries)):
            ck: str = entries[i][0]
            cv: int = entries[i][1]
            if v > cv or (v == cv and k < ck):
                entries.insert(i, entry)
                inserted = True
                break
        if not inserted:
            entries.append(entry)
    if n < 0:
        return entries
    out: list[tuple[str, int]] = []
    limit: int = min(n, len(entries))
    for j in range(limit):
        out.append(entries[j])
    return out
