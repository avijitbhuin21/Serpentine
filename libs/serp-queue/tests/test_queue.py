"""serp-queue differential test: identical output under CPython and native builds."""
from __future__ import annotations
from serpentine import Owned, PyVal, Thread
from serp_queue import Queue, LifoQueue, Empty, Full


def producer(start: int, count: int, q: Owned[Queue]) -> None:
    for i in range(count):
        q.put(start + i)
    q.put("done")


def consumer(q: Owned[Queue], out: Owned[Queue]) -> None:
    total: int = 0
    while True:
        item: PyVal = q.get()
        if item == "stop":
            q.task_done()
            break
        total = total + int(item)
        q.task_done()
    out.put(total)


def main() -> None:
    print("--- basics")
    q = Queue()
    print(q.qsize(), q.empty(), q.full(), q.maxsize)
    q.put(1)
    q.put("two")
    q.put([3, {"k": 4.5}])
    q.put_nowait(None)
    q.put(b"\x00five")
    print(q.qsize(), q.empty())
    print(q.get(), q.get(), q.get(), q.get(), q.get())
    print(q.empty())
    try:
        q.get_nowait()
    except Empty as e:
        print("Empty:", f"{e}")
    try:
        q.get(True, 0.01)
    except Empty:
        print("Empty on timeout")

    print("--- bounded")
    b = Queue(2)
    b.put(1)
    b.put(2)
    print(b.full(), b.qsize())
    try:
        b.put_nowait(3)
    except Full:
        print("Full")
    try:
        b.put(3, True, 0.01)
    except Full:
        print("Full on timeout")
    print(b.get(), b.full())
    b.put(3)
    print(b.get(), b.get())

    print("--- lifo")
    lq = LifoQueue()
    lq.put("a")
    lq.put("b")
    lq.put("c")
    print(lq.get(), lq.get(), lq.qsize())

    print("--- copies")
    src: PyVal = [1, 2]
    q.put(src)
    got: PyVal = q.get()
    print(got, got == src)

    print("--- threads")
    work = Queue()
    results = Queue()
    p1 = Thread(target=producer, args=(0, 50, work))
    p2 = Thread(target=producer, args=(100, 50, work))
    p1.start()
    p2.start()
    p1.join()
    p2.join()
    print(work.qsize())
    dones: int = 0
    kept = Queue()
    while not work.empty():
        item: PyVal = work.get_nowait()
        if item == "done":
            dones = dones + 1
        else:
            kept.put(item)
    print(dones, kept.qsize())
    c1 = Thread(target=consumer, args=(kept, results))
    c2 = Thread(target=consumer, args=(kept, results))
    c1.start()
    c2.start()
    kept.put("stop")
    kept.put("stop")
    kept.join()
    c1.join()
    c2.join()
    total: int = int(results.get()) + int(results.get())
    print(total, results.empty(), kept.empty())
    try:
        kept.task_done()
    except ValueError as e:
        print("ValueError:", e)
    print("done")


if __name__ == "__main__":
    main()
