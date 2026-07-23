"""serp-log — logging drop-in for the Serpentine subset.

The process-global logger registry and configuration live in the runtime
(serp_log_core, DECISIONS.md D12), so `getLogger("a.b")` behaves like
CPython's singleton registry even though Logger values are plain immutable
dataclasses (logger identity is unobservable — the subset has no `is` on
objects). Mirrors logging for the common surface: module-level
debug/info/warning/error/critical/log (with implicit basicConfig, like
CPython), getLogger + dotted-name effective-level inheritance,
Logger.setLevel/getEffectiveLevel/isEnabledFor, basicConfig(level=, format=,
filename=, filemode=) configure-once semantics, the last-resort
bare-message stderr handler when unconfigured, and getLevelName (incl.
"Level N"). Caps: messages are single pre-formatted strings (use f-strings —
no %-args), format supports the %(levelname)s/%(name)s/%(message)s fields,
console output goes to stderr like CPython, no Handler/Formatter/Filter
objects, no exception()/exc_info, no addLevelName/disable, and
getLogger("root") is the root logger.
"""
from __future__ import annotations
from serpentine import Ref, dataclass
from serp_log_core import lg_get, lg_set, lg_write_err

CRITICAL: int = 50
FATAL: int = 50
ERROR: int = 40
WARNING: int = 30
WARN: int = 30
INFO: int = 20
DEBUG: int = 10
NOTSET: int = 0

_DEFAULT_FORMAT: str = "%(levelname)s:%(name)s:%(message)s"


def getLevelName(level: int) -> str:
    """The textual name of a level, or 'Level N' like CPython."""
    if level == 50:
        return "CRITICAL"
    if level == 40:
        return "ERROR"
    if level == 30:
        return "WARNING"
    if level == 20:
        return "INFO"
    if level == 10:
        return "DEBUG"
    if level == 0:
        return "NOTSET"
    return f"Level {level}"


def _parent_name(name: str) -> str:
    """The dotted-name parent ('' when at the top)."""
    i: int = len(name) - 1
    while i >= 0:
        if name[i] == ".":
            return name[:i]
        i -= 1
    return ""


def _effective_level(name: str) -> int:
    """Walk the dotted hierarchy for the first explicit level, like CPython."""
    n: str = name
    while n != "" and n != "root":
        v: str = lg_get("level:" + n)
        if v != "":
            return int(v)
        n = _parent_name(n)
    rv: str = lg_get("level:root")
    if rv != "":
        return int(rv)
    return 30


def _emit(name: str, level: int, msg: str) -> None:
    """Send one record to the configured sink (or the last-resort handler)."""
    if lg_get("configured") == "1":
        fmt: str = lg_get("format")
        line: str = fmt.replace("%(levelname)s", getLevelName(level))
        line = line.replace("%(name)s", name)
        line = line.replace("%(message)s", msg)
        if lg_get("target") == "file":
            with open(lg_get("filename"), "a") as f:
                f.write(line + "\n")
        else:
            lg_write_err(line)
    else:
        if level >= 30:
            lg_write_err(msg)


@dataclass
class Logger:
    name: str

    @property
    def level(self: Ref[Logger]) -> int:
        v: str = lg_get("level:" + self.name)
        if v == "":
            return 30 if self.name == "root" else 0
        return int(v)

    def setLevel(self: Ref[Logger], level: int) -> None:
        lg_set("level:" + self.name, str(level))

    def getEffectiveLevel(self: Ref[Logger]) -> int:
        return _effective_level(self.name)

    def isEnabledFor(self: Ref[Logger], level: int) -> bool:
        return level >= self.getEffectiveLevel()

    def log(self: Ref[Logger], level: int, msg: str) -> None:
        if self.isEnabledFor(level):
            _emit(self.name, level, msg)

    def debug(self: Ref[Logger], msg: str) -> None:
        self.log(10, msg)

    def info(self: Ref[Logger], msg: str) -> None:
        self.log(20, msg)

    def warning(self: Ref[Logger], msg: str) -> None:
        self.log(30, msg)

    def error(self: Ref[Logger], msg: str) -> None:
        self.log(40, msg)

    def critical(self: Ref[Logger], msg: str) -> None:
        self.log(50, msg)


def getLogger(name: str = "") -> Logger:
    """Return the logger for a dotted name ('' or 'root' = the root logger)."""
    if name == "" or name == "root":
        return Logger("root")
    return Logger(name)


def basicConfig(level: int = -1, format: str = "", filename: str = "",
                filemode: str = "a") -> None:
    """Configure the root sink once, like logging.basicConfig."""
    if lg_get("configured") == "1":
        return
    lg_set("configured", "1")
    if filename != "":
        lg_set("target", "file")
        lg_set("filename", filename)
        if filemode == "w":
            with open(filename, "w") as f:
                f.write("")
    else:
        lg_set("target", "stderr")
    fmt: str = format if format != "" else _DEFAULT_FORMAT
    lg_set("format", fmt)
    if level >= 0:
        lg_set("level:root", str(level))


def log(level: int, msg: str) -> None:
    """Module-level log via the root logger (configures implicitly)."""
    basicConfig()
    root: Logger = getLogger("")
    root.log(level, msg)


def debug(msg: str) -> None:
    log(10, msg)


def info(msg: str) -> None:
    log(20, msg)


def warning(msg: str) -> None:
    log(30, msg)


def error(msg: str) -> None:
    log(40, msg)


def critical(msg: str) -> None:
    log(50, msg)


def level_name(level: int) -> str:
    """Legacy helper: coarse level bucket name."""
    if level >= 40:
        return "ERROR"
    if level >= 30:
        return "WARNING"
    if level >= 20:
        return "INFO"
    return "DEBUG"


def log_line(name: str, level: int, msg: str) -> str:
    """Legacy helper: the original '[LEVEL] name: msg' line format."""
    return f"[{level_name(level)}] {name}: {msg}"


def make_logger(name: str, level: int) -> Logger:
    """Legacy helper: a logger with an explicit level already set."""
    lg: Logger = getLogger(name)
    lg.setLevel(level)
    return lg


def append_log(path: str, line: str) -> None:
    """Legacy helper: append one line to a log file."""
    with open(path, "a") as f:
        n: int = f.write(line + "\n")
