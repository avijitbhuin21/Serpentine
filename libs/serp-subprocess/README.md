# serp-subprocess

Drop-in replacement for CPython's `subprocess` (core surface). Native builds
spawn children through the runtime (`std::process` + platform pipes, no
crates); under CPython the `serp_subprocess_core` delegate drives stdlib
`subprocess.Popen` through the same handle API, so output is byte-identical
across both worlds.

## API

- `run(args, *, stdin, input, stdout, stderr, capture_output, shell, cwd,
  timeout, check, env, text)` → `CompletedProcess(args, returncode, stdout, stderr)`
  with `.check_returncode()` and CPython's repr.
- `check_output(args, ...)`, `check_call(args, ...)`, `call(args, ...)`.
- `Popen(args, stdin, stdout, stderr, shell, cwd, env, text)` with
  `.communicate(input, timeout)`, `.wait(timeout)`, `.poll()`, `.kill()`,
  `.terminate()`, `.pid`, `.returncode`, and `with` support.
- `PIPE`, `STDOUT`, `DEVNULL`; `SubprocessError`, `CalledProcessError`,
  `TimeoutExpired` (messages match CPython's wording).
- `text=True` decodes UTF-8 and applies universal newlines; `env=` is a full
  replacement mapping; `shell=True` runs through `cmd /c` on Windows and
  `/bin/sh -c` elsewhere.

Divergences: exceptions carry only their message (no `.returncode`/`.output`
attributes); `communicate()` returns a tuple to index (`res[0]`, `res[1]`) since
tuple unpacking is outside the subset; `timeout` renders as a float in the
`TimeoutExpired` message; spawn failures use normalized messages instead of
CPython's `[Errno N]`/`[WinError N]` texts; no `encoding=`/`errors=`/`bufsize=`,
no streaming `.stdout` file objects, no `preexec_fn`/`start_new_session`.

## Install

```
serp add serp-subprocess
pip install serp-subprocess
```
