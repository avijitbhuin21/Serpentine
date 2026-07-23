"""serp-cli — argparse drop-in plus the original argparse-lite Cli.

Pure Serpentine ([P]). ArgumentParser mirrors argparse for the common
surface: add_argument() with short/long option strings, store/store_true/
store_false actions, defaults, required, help text; parse_args() returns a
dict-shaped Namespace (PyVal) — read values with args["dest"] indexing
(attribute access on a dynamic value is not in the subset; the documented
divergence). -h/--help prints help and exits 0; parse errors print usage
plus "prog: error: ..." and exit 2 (to stdout — the subset has no stderr).
Caps: no nargs/type/choices/metavar/subparsers, no fused or '='-joined
short options, help layout approximates CPython 3.11 without line wrapping.
Legacy API: build a Cli with new_cli(), declare flags, options, positionals
and subcommands, then parse(argv) into a ParseResult.
"""
from __future__ import annotations
import sys
from serpentine import Ref, Mut, PyVal, dataclass, pyval_kind


@dataclass
class Cli:
    prog: str
    description: str
    flag_names: list[str]
    flag_help: list[str]
    opt_names: list[str]
    opt_defaults: list[str]
    opt_help: list[str]
    pos_names: list[str]
    pos_help: list[str]
    commands: list[str]

    def add_flag(self: Mut[Cli], name: str, help_text: str) -> None:
        self.flag_names.append(name)
        self.flag_help.append(help_text)

    def add_opt(self: Mut[Cli], name: str, default: str, help_text: str) -> None:
        self.opt_names.append(name)
        self.opt_defaults.append(default)
        self.opt_help.append(help_text)

    def add_pos(self: Mut[Cli], name: str, help_text: str) -> None:
        self.pos_names.append(name)
        self.pos_help.append(help_text)

    def add_command(self: Mut[Cli], name: str) -> None:
        self.commands.append(name)

    def parse(self: Ref[Cli], args: Ref[list[str]]) -> ParseResult:
        res: ParseResult = ParseResult(True, "", False, "", {}, {}, {}, [])
        for i0 in range(len(self.flag_names)):
            res.flags[self.flag_names[i0]] = False
        for i1 in range(len(self.opt_names)):
            res.opts[self.opt_names[i1]] = self.opt_defaults[i1]
        positional: list[str] = []
        i: int = 0
        n: int = len(args)
        while i < n:
            arg: str = args[i]
            if arg == "-h" or arg == "--help":
                res.help_requested = True
                i += 1
            elif arg.startswith("--"):
                body: str = arg[2:]
                eq: int = body.find("=")
                inline: str = ""
                has_inline: bool = False
                if eq >= 0:
                    inline = body[eq + 1:]
                    body = body[:eq]
                    has_inline = True
                if _contains(self.flag_names, body):
                    if has_inline:
                        res.ok = False
                        res.error = f"flag --{body} does not take a value"
                        return res
                    res.flags[body] = True
                    i += 1
                elif _contains(self.opt_names, body):
                    if has_inline:
                        res.opts[body] = inline
                        i += 1
                    elif i + 1 < n:
                        res.opts[body] = args[i + 1]
                        i += 2
                    else:
                        res.ok = False
                        res.error = f"option --{body} needs a value"
                        return res
                else:
                    res.ok = False
                    res.error = f"unknown option --{body}"
                    return res
            else:
                positional.append(arg)
                i += 1
        idx: int = 0
        if len(self.commands) > 0:
            if len(positional) == 0:
                if not res.help_requested:
                    res.ok = False
                    res.error = "missing command"
                return res
            cmd: str = positional[0]
            if not _contains(self.commands, cmd):
                res.ok = False
                res.error = f"unknown command {cmd!r}"
                return res
            res.command = cmd
            idx = 1
        for p in range(len(self.pos_names)):
            if idx < len(positional):
                res.pos[self.pos_names[p]] = positional[idx]
                idx += 1
            elif not res.help_requested:
                res.ok = False
                res.error = f"missing argument {self.pos_names[p]!r}"
                return res
        while idx < len(positional):
            res.extras.append(positional[idx])
            idx += 1
        return res

    def usage(self: Ref[Cli]) -> str:
        lines: list[str] = []
        head: str = f"usage: {self.prog}"
        if len(self.commands) > 0:
            head = head + " COMMAND"
        if len(self.flag_names) > 0 or len(self.opt_names) > 0:
            head = head + " [options]"
        for p in self.pos_names:
            head = head + f" {p.upper()}"
        lines.append(head)
        if self.description != "":
            lines.append("")
            lines.append(self.description)
        if len(self.commands) > 0:
            lines.append("")
            lines.append("commands: " + ", ".join(self.commands))
        if len(self.pos_names) > 0:
            lines.append("")
            lines.append("arguments:")
            for i in range(len(self.pos_names)):
                lines.append("  " + _pad(self.pos_names[i].upper(), 18) + self.pos_help[i])
        lines.append("")
        lines.append("options:")
        for j in range(len(self.flag_names)):
            lines.append("  " + _pad("--" + self.flag_names[j], 18) + self.flag_help[j])
        for k in range(len(self.opt_names)):
            label: str = "--" + self.opt_names[k] + " VALUE"
            lines.append("  " + _pad(label, 18) + self.opt_help[k]
                         + f" (default: {self.opt_defaults[k]!r})")
        lines.append("  " + _pad("-h, --help", 18) + "show this help text")
        return "\n".join(lines)


@dataclass
class ParseResult:
    ok: bool
    error: str
    help_requested: bool
    command: str
    flags: dict[str, bool]
    opts: dict[str, str]
    pos: dict[str, str]
    extras: list[str]


def new_cli(prog: str, description: str) -> Cli:
    return Cli(prog, description, [], [], [], [], [], [], [], [])


def _contains(xs: Ref[list[str]], v: str) -> bool:
    for x in xs:
        if x == v:
            return True
    return False


def _pad(s: str, width: int) -> str:
    out: str = s
    while len(out) < width:
        out = out + " "
    return out


@dataclass
class ArgumentParser:
    prog: str = ""
    description: str = ""
    arg_short: list[str] = []
    arg_long: list[str] = []
    arg_dest: list[str] = []
    arg_action: list[str] = []
    arg_default: list[PyVal] = []
    arg_help: list[str] = []
    arg_required: list[bool] = []
    arg_positional: list[bool] = []

    def add_argument(self: Mut[ArgumentParser], name: str, alt: str = "",
                     action: str = "store", default: PyVal = None,
                     help: str = "", required: bool = False) -> None:
        short: str = ""
        long: str = ""
        positional: bool = False
        if name.startswith("--"):
            long = name
        elif name.startswith("-"):
            short = name
            if alt.startswith("--"):
                long = alt
        else:
            positional = True
        source: str = long if long != "" else (short if short != "" else name)
        body: str = source
        while body.startswith("-"):
            body = body[1:]
        dest: str = body.replace("-", "_")
        self.arg_short.append(short)
        self.arg_long.append(long)
        self.arg_dest.append(dest)
        self.arg_action.append(action)
        self.arg_default.append(default)
        self.arg_help.append(help)
        self.arg_required.append(required or positional)
        self.arg_positional.append(positional)

    def _prog_name(self: Ref[ArgumentParser]) -> str:
        if self.prog != "":
            return self.prog
        path: str = sys.argv[0]
        i: int = len(path) - 1
        while i >= 0:
            c: str = path[i]
            if c == "/" or c == "\\":
                return path[i + 1:]
            i -= 1
        return path

    def _default_value(self: Ref[ArgumentParser], i: int) -> PyVal:
        if self.arg_action[i] == "store_true":
            d: PyVal = self.arg_default[i]
            if pyval_kind(d) == "NoneType":
                return False
            return d
        if self.arg_action[i] == "store_false":
            d2: PyVal = self.arg_default[i]
            if pyval_kind(d2) == "NoneType":
                return True
            return d2
        return self.arg_default[i]

    def _find_long(self: Ref[ArgumentParser], token: str) -> int:
        for i in range(len(self.arg_long)):
            if not self.arg_positional[i] and self.arg_long[i] == token:
                return i
        return -1

    def _find_short(self: Ref[ArgumentParser], token: str) -> int:
        for i in range(len(self.arg_short)):
            if not self.arg_positional[i] and self.arg_short[i] == token:
                return i
        return -1

    def _display_name(self: Ref[ArgumentParser], i: int) -> str:
        if self.arg_positional[i]:
            return self.arg_dest[i]
        names: list[str] = []
        if self.arg_short[i] != "":
            names.append(self.arg_short[i])
        if self.arg_long[i] != "":
            names.append(self.arg_long[i])
        return "/".join(names)

    def format_usage(self: Ref[ArgumentParser]) -> str:
        head: str = f"usage: {self._prog_name()} [-h]"
        for i in range(len(self.arg_dest)):
            if self.arg_positional[i]:
                continue
            first: str = self.arg_short[i] if self.arg_short[i] != "" else self.arg_long[i]
            piece: str = first
            if self.arg_action[i] == "store":
                piece = f"{first} {self.arg_dest[i].upper()}"
            if self.arg_required[i]:
                head = head + " " + piece
            else:
                head = head + " [" + piece + "]"
        for j in range(len(self.arg_dest)):
            if self.arg_positional[j]:
                head = head + " " + self.arg_dest[j]
        return head

    def _invocation(self: Ref[ArgumentParser], i: int) -> str:
        if self.arg_positional[i]:
            return self.arg_dest[i]
        names: list[str] = []
        metavar: str = self.arg_dest[i].upper()
        if self.arg_short[i] != "":
            if self.arg_action[i] == "store":
                names.append(f"{self.arg_short[i]} {metavar}")
            else:
                names.append(self.arg_short[i])
        if self.arg_long[i] != "":
            if self.arg_action[i] == "store":
                names.append(f"{self.arg_long[i]} {metavar}")
            else:
                names.append(self.arg_long[i])
        return ", ".join(names)

    def format_help(self: Ref[ArgumentParser]) -> str:
        lines: list[str] = [self.format_usage()]
        if self.description != "":
            lines.append("")
            lines.append(self.description)
        width: int = len("-h, --help")
        for i in range(len(self.arg_dest)):
            inv: str = self._invocation(i)
            if len(inv) > width:
                width = len(inv)
        has_pos: bool = False
        for i2 in range(len(self.arg_dest)):
            if self.arg_positional[i2]:
                has_pos = True
        if has_pos:
            lines.append("")
            lines.append("positional arguments:")
            for p in range(len(self.arg_dest)):
                if self.arg_positional[p]:
                    lines.append(_help_row(self._invocation(p), self.arg_help[p], width))
        lines.append("")
        lines.append("options:")
        lines.append(_help_row("-h, --help", "show this help message and exit", width))
        for o in range(len(self.arg_dest)):
            if not self.arg_positional[o]:
                lines.append(_help_row(self._invocation(o), self.arg_help[o], width))
        return "\n".join(lines)

    def print_help(self: Ref[ArgumentParser]) -> None:
        print(self.format_help())

    def error(self: Ref[ArgumentParser], message: str) -> None:
        print(self.format_usage())
        print(f"{self._prog_name()}: error: {message}")
        sys.exit(2)

    def parse_args(self: Ref[ArgumentParser], args: PyVal = None) -> PyVal:
        argv: list[str] = []
        if pyval_kind(args) == "NoneType":
            raw: list[str] = sys.argv
            for a0 in range(1, len(raw)):
                argv.append(raw[a0])
        else:
            for item in args:
                argv.append(str(item))
        ns: dict[str, PyVal] = {}
        for d in range(len(self.arg_dest)):
            ns[self.arg_dest[d]] = self._default_value(d)
        seen: list[bool] = []
        for _s in range(len(self.arg_dest)):
            seen.append(False)
        positional: list[str] = []
        i: int = 0
        n: int = len(argv)
        while i < n:
            arg: str = argv[i]
            if arg == "-h" or arg == "--help":
                self.print_help()
                sys.exit(0)
            if arg.startswith("--"):
                body: str = arg
                inline: str = ""
                has_inline: bool = False
                eq: int = arg.find("=")
                if eq >= 0:
                    body = arg[:eq]
                    inline = arg[eq + 1:]
                    has_inline = True
                k: int = self._find_long(body)
                if k < 0:
                    self.error(f"unrecognized arguments: {arg}")
                if self.arg_action[k] == "store":
                    if has_inline:
                        ns[self.arg_dest[k]] = inline
                        i += 1
                    elif i + 1 < n:
                        ns[self.arg_dest[k]] = argv[i + 1]
                        i += 2
                    else:
                        self.error(f"argument {self._display_name(k)}: expected one argument")
                else:
                    if has_inline:
                        self.error(f"argument {self._display_name(k)}: ignored explicit "
                                   f"argument {inline!r}")
                    ns[self.arg_dest[k]] = self.arg_action[k] == "store_true"
                    i += 1
                seen[k] = True
            elif arg.startswith("-") and len(arg) > 1:
                k2: int = self._find_short(arg)
                if k2 < 0:
                    self.error(f"unrecognized arguments: {arg}")
                if self.arg_action[k2] == "store":
                    if i + 1 < n:
                        ns[self.arg_dest[k2]] = argv[i + 1]
                        i += 2
                    else:
                        self.error(f"argument {self._display_name(k2)}: expected one argument")
                else:
                    ns[self.arg_dest[k2]] = self.arg_action[k2] == "store_true"
                    i += 1
                seen[k2] = True
            else:
                positional.append(arg)
                i += 1
        idx: int = 0
        for p in range(len(self.arg_dest)):
            if self.arg_positional[p] and idx < len(positional):
                ns[self.arg_dest[p]] = positional[idx]
                seen[p] = True
                idx += 1
        if idx < len(positional):
            extras: list[str] = []
            while idx < len(positional):
                extras.append(positional[idx])
                idx += 1
            self.error("unrecognized arguments: " + " ".join(extras))
        missing: list[str] = []
        for m in range(len(self.arg_dest)):
            if self.arg_required[m] and not seen[m]:
                missing.append(self._display_name(m))
        if len(missing) > 0:
            self.error("the following arguments are required: " + ", ".join(missing))
        return ns


def _help_row(invocation: str, help_text: str, width: int) -> str:
    """Format one help line with argparse-style two-space indent and alignment."""
    if help_text == "":
        return "  " + invocation
    return "  " + _pad(invocation, width + 2) + help_text