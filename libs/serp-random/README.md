# serp-random

Drop-in replacement for CPython's `random` module (docs/libraries.md drop-in facade push).

- `from serp_random import seed, random, randint, uniform, randrange, getrandbits, choice, shuffle`
- The generator is **MT19937 (Mersenne Twister)**, implemented bit-for-bit like CPython:
  the same seeding (`init_by_array` over the integer's 32-bit limbs), `genrand_res53`
  floats, and `_randbelow` rejection sampling. A seeded sequence is **identical to
  CPython's `random` module** — and therefore byte-identical across native builds and
  CPython runs.
- `seed()` with no argument seeds from OS entropy; `seed(n)` is reproducible.
- Architecture: `serp_random` is a pure-Serpentine facade over the compiler-known
  `serp_random_core` rtlib module (MT19937 lives in the native runtime; the CPython
  delegate drives the stdlib's global Mersenne Twister).
- Divergences: `getrandbits(k)` caps at 63 bits (native int64); randrange/randint
  widths must fit in int64; error messages pinned to CPython 3.11; `sample`,
  `choices`, the distribution functions, and the `Random` class are not provided.
- `choice`/`shuffle` work with lists of Copy elements (int/float/str/bool/bytes).

Install into a Serpentine project with `serp add serp-random`.
