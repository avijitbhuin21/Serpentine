"""serp-subprocess — drop-in `subprocess` facade over serp_subprocess_core.

Pure Serpentine ([P] over the serp_subprocess_core rtlib module): the same
source compiles natively and imports under CPython. Stdlib names and shapes:
`run()`, `check_output()`, `check_call()`, `call()`, `Popen` (communicate/
wait/poll/kill/terminate/pid/returncode, context manager), `CompletedProcess`,
`CalledProcessError`, `TimeoutExpired`, `PIPE`/`STDOUT`/`DEVNULL`.

`args` is a list of strings (or a single string with `shell=True`); `env` is a
full replacement mapping like CPython. `text=True` decodes UTF-8 and applies
universal newlines. Divergences: exceptions carry only their message (no
`.returncode`/`.output` attributes); `communicate()` returns a tuple to index
(tuple unpacking is outside the subset); `timeout` is always formatted as a
float in the TimeoutExpired message; spawn errors are normalized (not
CPython's `[Errno N]`/`[WinError N]` texts).
"""
from __future__ import annotations
from serpentine import Mut, Ref, PyVal, pyval_kind, dataclass
from serp_subprocess_core import sp_spawn as _core_spawn, sp_pid as _core_pid
from serp_subprocess_core import sp_communicate as _core_communicate, sp_wait as _core_wait
from serp_subprocess_core import sp_poll as _core_poll, sp_returncode as _core_returncode
from serp_subprocess_core import sp_stdout as _core_stdout, sp_stderr as _core_stderr
from serp_subprocess_core import sp_kill as _core_kill, sp_terminate as _core_terminate
from serp_subprocess_core import sp_free as _core_free

PIPE: int = -1
STDOUT: int = -2
DEVNULL: int = -3


class SubprocessError(Exception):
    pass


class CalledProcessError(SubprocessError):
    pass


class TimeoutExpired(SubprocessError):
    pass


def _argv(args: PyVal) -> list[str]:
    """Normalize `args` (str or list of str) to an argv list."""
    out: list[str] = []
    if pyval_kind(args) == "str":
        out.append(str(args))
        return out
    for a in args:
        out.append(str(a))
    return out


def _env_joined(env: PyVal) -> str:
    """NUL-join a mapping as KEY=VALUE entries for the runtime."""
    parts: list[str] = []
    for k in env:
        parts.append(f"{k}={env[k]}")
    return "\x00".join(parts)


def _stdio_flags(stdin: int | None, stdout: int | None, stderr: int | None) -> int:
    """Encode the three stdio choices as runtime flag bits."""
    flags: int = 0
    if stdin == PIPE:
        flags += 1
    elif stdin == DEVNULL:
        flags += 64
    if stdout == PIPE:
        flags += 2
    elif stdout == DEVNULL:
        flags += 128
    if stderr == PIPE:
        flags += 4
    elif stderr == STDOUT:
        flags += 8
    elif stderr == DEVNULL:
        flags += 256
    return flags


def _signal_text(code: int) -> str:
    """CPython's `<Signals.NAME: N>` rendering for a negative return code."""
    n: int = -code
    names: dict[int, str] = {1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 6: "SIGABRT",
                             9: "SIGKILL", 11: "SIGSEGV", 13: "SIGPIPE", 14: "SIGALRM",
                             15: "SIGTERM"}
    if n in names:
        return f"<Signals.{names[n]}: {n}>"
    return f"unknown signal {n}"


def _called_msg(args: PyVal, code: int) -> str:
    """CalledProcessError message with CPython's wording."""
    if code < 0:
        return f"Command '{args}' died with {_signal_text(code)}."
    return f"Command '{args}' returned non-zero exit status {code}."


def _timeout_msg(args: PyVal, timeout: float) -> str:
    """TimeoutExpired message with CPython's wording."""
    return f"Command '{args}' timed out after {timeout} seconds"


@dataclass
class CompletedProcess:
    args: PyVal
    returncode: int
    stdout: str | bytes | None
    stderr: str | bytes | None

    def check_returncode(self: Ref[CompletedProcess]) -> None:
        """Raise CalledProcessError when the exit status is non-zero."""
        if self.returncode != 0:
            raise CalledProcessError(_called_msg(self.args, self.returncode))

    def __repr__(self: Ref[CompletedProcess]) -> str:
        parts: list[str] = [f"args={self.args!r}", f"returncode={self.returncode!r}"]
        if self.stdout is not None:
            parts.append(f"stdout={self.stdout!r}")
        if self.stderr is not None:
            parts.append(f"stderr={self.stderr!r}")
        return "CompletedProcess(" + ", ".join(parts) + ")"


@dataclass
class Popen:
    args: PyVal
    pid: int
    returncode: int | None
    _h: int
    _text: bool
    _out_piped: bool
    _err_piped: bool

    def __init__(self: Mut[Popen], args: PyVal, stdin: int | None = None,
                 stdout: int | None = None, stderr: int | None = None,
                 shell: bool = False, cwd: str | None = None, env: PyVal | None = None,
                 text: bool = False) -> None:
        flags: int = _stdio_flags(stdin, stdout, stderr)
        if shell:
            flags += 16
        env_s: str = ""
        if env is not None:
            flags += 32
            env_s = _env_joined(env)
        cwd_s: str = ""
        if cwd is not None:
            cwd_s = cwd
        self.args = args
        self._text = text
        self._out_piped = stdout == PIPE
        self._err_piped = stderr == PIPE
        self.returncode = None
        self._h = _core_spawn("\x00".join(_argv(args)), cwd_s, env_s, flags)
        self.pid = _core_pid(self._h)

    def _decode(self: Ref[Popen], raw: bytes) -> str | bytes | None:
        """Apply text mode (UTF-8 + universal newlines) to captured output."""
        if self._text:
            return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        return raw

    def communicate(self: Mut[Popen], input: bytes | str | None = None,
                    timeout: float | None = None) -> tuple[str | bytes | None, str | bytes | None]:
        """Send input, drain the pipes and wait; returns (stdout, stderr)."""
        data: bytes = b""
        has_input: int = 0
        if isinstance(input, str):
            data = input.encode("utf-8")
            has_input = 1
        if isinstance(input, bytes):
            data = input
            has_input = 1
        ms: int = -1
        secs: float = 0.0
        if timeout is not None:
            secs = timeout
            ms = int(timeout * 1000.0)
        done: bool = _core_communicate(self._h, data, has_input, ms)
        if not done:
            raise TimeoutExpired(_timeout_msg(self.args, secs))
        self.returncode = _core_returncode(self._h)
        out: str | bytes | None = None
        err: str | bytes | None = None
        if self._out_piped:
            out = self._decode(_core_stdout(self._h))
        if self._err_piped:
            err = self._decode(_core_stderr(self._h))
        return (out, err)

    def wait(self: Mut[Popen], timeout: float | None = None) -> int:
        """Wait for the child to exit and return its code."""
        ms: int = -1
        secs: float = 0.0
        if timeout is not None:
            secs = timeout
            ms = int(timeout * 1000.0)
        done: bool = _core_wait(self._h, ms)
        if not done:
            raise TimeoutExpired(_timeout_msg(self.args, secs))
        code: int = _core_returncode(self._h)
        self.returncode = code
        return code

    def poll(self: Mut[Popen]) -> int | None:
        """Return the exit code if the child has exited, else None."""
        if _core_poll(self._h):
            code: int = _core_returncode(self._h)
            self.returncode = code
            return code
        return None

    def kill(self: Ref[Popen]) -> None:
        """Kill the child."""
        _core_kill(self._h)

    def terminate(self: Ref[Popen]) -> None:
        """Terminate the child (SIGTERM; same as kill() on Windows)."""
        _core_terminate(self._h)

    def __enter__(self: Ref[Popen]) -> Popen:
        return self

    def __exit__(self: Mut[Popen], exc_type: None, exc: None, tb: None) -> None:
        if self.returncode is None:
            self.wait(None)
        _core_free(self._h)


def run(args: PyVal, stdin: int | None = None, input: bytes | str | None = None,
        stdout: int | None = None, stderr: int | None = None,
        capture_output: bool = False, shell: bool = False, cwd: str | None = None,
        timeout: float | None = None, check: bool = False, env: PyVal | None = None,
        text: bool = False) -> CompletedProcess:
    """Run a command to completion and return a CompletedProcess."""
    if input is not None:
        if stdin is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        stdin = PIPE
    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        stdout = PIPE
        stderr = PIPE
    p: Popen = Popen(args, stdin=stdin, stdout=stdout, stderr=stderr, shell=shell,
                     cwd=cwd, env=env, text=text)
    timed_out: bool = False
    out: str | bytes | None = None
    err: str | bytes | None = None
    try:
        res = p.communicate(input, timeout)
        out = res[0]
        err = res[1]
    except TimeoutExpired:
        timed_out = True
    if timed_out:
        p.kill()
        p.communicate(None, None)
        _core_free(p._h)
        secs: float = 0.0
        if timeout is not None:
            secs = timeout
        raise TimeoutExpired(_timeout_msg(args, secs))
    code: int = 0
    rc = p.returncode
    if rc is not None:
        code = rc
    _core_free(p._h)
    if check and code != 0:
        raise CalledProcessError(_called_msg(args, code))
    return CompletedProcess(args, code, out, err)


def check_output(args: PyVal, input: bytes | str | None = None, stderr: int | None = None,
                 shell: bool = False, cwd: str | None = None, timeout: float | None = None,
                 env: PyVal | None = None, text: bool = False) -> str | bytes:
    """Run a command, raise on non-zero exit, and return its captured stdout."""
    r: CompletedProcess = run(args, input=input, stdout=PIPE, stderr=stderr, shell=shell,
                              cwd=cwd, timeout=timeout, check=True, env=env, text=text)
    out = r.stdout
    if isinstance(out, str):
        return out
    if isinstance(out, bytes):
        return out
    return b""


def call(args: PyVal, stdin: int | None = None, stdout: int | None = None,
         stderr: int | None = None, shell: bool = False, cwd: str | None = None,
         timeout: float | None = None, env: PyVal | None = None) -> int:
    """Run a command and return its exit code."""
    r: CompletedProcess = run(args, stdin=stdin, stdout=stdout, stderr=stderr, shell=shell,
                              cwd=cwd, timeout=timeout, env=env)
    return r.returncode


def check_call(args: PyVal, stdin: int | None = None, stdout: int | None = None,
               stderr: int | None = None, shell: bool = False, cwd: str | None = None,
               timeout: float | None = None, env: PyVal | None = None) -> int:
    """Run a command, raise CalledProcessError on non-zero exit, return 0."""
    r: CompletedProcess = run(args, stdin=stdin, stdout=stdout, stderr=stderr, shell=shell,
                              cwd=cwd, timeout=timeout, check=True, env=env)
    return r.returncode
