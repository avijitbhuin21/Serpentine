"""serp-subprocess-core CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_subprocess_core import ...` (rtlib.py); under
CPython these drive stdlib `subprocess.Popen` through the same handle-based
API the runtime exposes. Error messages are normalized identically to
prelude.rs so dual runs stay byte-identical.
"""

import os as _os
import subprocess as _sp
import sys as _sys
import threading as _threading

__all__ = ["sp_spawn", "sp_pid", "sp_communicate", "sp_wait", "sp_poll",
           "sp_returncode", "sp_stdout", "sp_stderr", "sp_kill", "sp_terminate",
           "sp_free"]

_STDIN_PIPE = 1
_STDOUT_PIPE = 2
_STDERR_PIPE = 4
_STDERR_TO_STDOUT = 8
_SHELL = 16
_ENV = 32
_STDIN_DEVNULL = 64
_STDOUT_DEVNULL = 128
_STDERR_DEVNULL = 256


class _Proc:
    """One spawned child plus its drained output and exit state."""

    def __init__(self, popen):
        self.p = popen
        self.out_thread = None
        self.err_thread = None
        self.stdout = b""
        self.stderr = b""
        self.code = None
        self.started = False


_PROCS = []


def _proc(h):
    """Resolve a handle to its record."""
    if h < 1 or h > len(_PROCS):
        raise ValueError("invalid process handle")
    rec = _PROCS[h - 1]
    if rec is None:
        raise ValueError("process handle already closed")
    return rec


def _pick(flags, pipe_bit, null_bit):
    """Translate flag bits to a Popen stdio argument."""
    if flags & pipe_bit:
        return _sp.PIPE
    if flags & null_bit:
        return _sp.DEVNULL
    return None


def sp_spawn(argv, cwd, env, flags):
    """Start a child; argv/env are NUL-joined; returns a handle."""
    parts = argv.split("\x00") if argv else []
    shell = bool(flags & _SHELL)
    if shell:
        args = " ".join(parts)
    else:
        if not parts:
            raise IndexError("list index out of range")
        args = parts
    kw = {}
    if cwd:
        kw["cwd"] = cwd
    if flags & _ENV:
        mapping = {}
        if env:
            for kv in env.split("\x00"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    mapping[k] = v
        kw["env"] = mapping
    stdin = _pick(flags, _STDIN_PIPE, _STDIN_DEVNULL)
    stdout = _pick(flags, _STDOUT_PIPE, _STDOUT_DEVNULL)
    if flags & _STDERR_TO_STDOUT:
        stderr = _sp.STDOUT
    else:
        stderr = _pick(flags, _STDERR_PIPE, _STDERR_DEVNULL)
    prog = "sh" if shell else parts[0]
    try:
        p = _sp.Popen(args, stdin=stdin, stdout=stdout, stderr=stderr, shell=shell, **kw)
    except FileNotFoundError:
        raise FileNotFoundError(f"No such file or directory: {prog!r}")
    except PermissionError:
        raise PermissionError(f"Permission denied: {prog!r}")
    except OSError:
        raise OSError(f"could not start process: {prog!r}")
    _PROCS.append(_Proc(p))
    return len(_PROCS)


def sp_pid(h):
    """Child process id."""
    return _proc(h).p.pid


def _drain(stream, sink, key):
    """Read a pipe to EOF on a helper thread."""
    def go():
        try:
            sink[key] = stream.read()
        finally:
            stream.close()
    t = _threading.Thread(target=go, daemon=True)
    t.start()
    return t


def _record_exit(rec):
    """Store the exit code and join the drain threads."""
    code = rec.p.returncode
    if _sys.platform == "win32":
        code = code & 0xFFFFFFFF
    rec.code = code
    if rec.out_thread is not None:
        rec.out_thread.join()
        rec.stdout = rec._sink.get("out", b"")
        rec.out_thread = None
    if rec.err_thread is not None:
        rec.err_thread.join()
        rec.stderr = rec._sink.get("err", b"")
        rec.err_thread = None


def _wait_until(rec, timeout_ms):
    """Wait for exit (timeout_ms < 0 blocks); True when the child has exited."""
    if rec.code is not None:
        return True
    try:
        rec.p.wait(timeout=None if timeout_ms < 0 else timeout_ms / 1000.0)
    except _sp.TimeoutExpired:
        return False
    _record_exit(rec)
    return True


def sp_communicate(h, input, has_input, timeout_ms):
    """Feed stdin, drain stdout/stderr, wait; False when the timeout elapsed."""
    rec = _proc(h)
    if not rec.started:
        rec.started = True
        rec._sink = {}
        if rec.p.stdout is not None:
            rec.out_thread = _drain(rec.p.stdout, rec._sink, "out")
        if rec.p.stderr is not None:
            rec.err_thread = _drain(rec.p.stderr, rec._sink, "err")
        if rec.p.stdin is not None:
            try:
                if has_input:
                    rec.p.stdin.write(input)
                rec.p.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                rec.p.stdin.close()
            except OSError:
                pass
    return _wait_until(rec, timeout_ms)


def sp_wait(h, timeout_ms):
    """Wait for exit without touching pipes; False when the timeout elapsed."""
    return _wait_until(_proc(h), timeout_ms)


def sp_poll(h):
    """True when the child has exited (records the code)."""
    rec = _proc(h)
    if rec.code is not None:
        return True
    if rec.p.poll() is None:
        return False
    _record_exit(rec)
    return True


def sp_returncode(h):
    """Exit code after wait/communicate/poll reported exit."""
    rec = _proc(h)
    if rec.code is None:
        raise ValueError("process has not exited")
    return rec.code


def sp_stdout(h):
    """Drained stdout bytes (empty until communicate finished)."""
    return _proc(h).stdout


def sp_stderr(h):
    """Drained stderr bytes (empty until communicate finished)."""
    return _proc(h).stderr


def sp_kill(h):
    """Kill the child (no-op once exited)."""
    rec = _proc(h)
    if rec.code is None:
        try:
            rec.p.kill()
        except OSError:
            pass


def sp_terminate(h):
    """Terminate the child (SIGTERM; same as kill on Windows)."""
    rec = _proc(h)
    if rec.code is None:
        try:
            rec.p.terminate()
        except OSError:
            pass


def sp_free(h):
    """Release the handle slot."""
    if 1 <= h <= len(_PROCS):
        _PROCS[h - 1] = None
