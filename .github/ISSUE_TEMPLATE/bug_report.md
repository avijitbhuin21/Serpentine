---
name: Bug report
about: Something compiles wrong, crashes, or differs from CPython
labels: bug
---

**What happened**

<!-- One or two sentences. -->

**Reproducer**

```python
# the smallest .py file that shows the problem
```

**Output**

- CPython (`python file.py`):
- Native (`serp build file.py && ./file`):
- Or the `serp check` / `serp build` error:

**Environment**

- `serp --version`:
- Backend: llvm (default) / rust, debug or release:
- OS and architecture:
- `python --version` and `rustc --version`:
