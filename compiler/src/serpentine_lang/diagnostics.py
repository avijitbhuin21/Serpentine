"""Diagnostics v1: stable error codes, source spans, primary labels."""

from dataclasses import dataclass, field


@dataclass
class Span:
    """A source location: file, 1-indexed line, 0-indexed column."""

    file: str
    line: int
    col: int
    end_col: int | None = None


@dataclass
class Diagnostic:
    """A single checker error with its stable code and primary label."""

    code: str
    name: str
    message: str
    span: Span
    label: str = ""
    secondary: list = field(default_factory=list)   # list[(Span, str)]
    help: str = ""

    def render(self, source_lines: dict[str, list[str]] | None = None) -> str:
        """Render the diagnostic in rustc-style layout with source lines and carets."""
        out = [f"error[{self.code}]: {self.message}"]
        out.append(f"  --> {self.span.file}:{self.span.line}:{self.span.col + 1}")
        self._render_snippet(out, self.span, self.label, "^", source_lines)
        for (span, label) in self.secondary:
            out.append(f"  --> {span.file}:{span.line}:{span.col + 1}")
            self._render_snippet(out, span, label, "-", source_lines)
        if self.help:
            out.append(f"  help: {self.help}")
        return "\n".join(out)

    def _render_snippet(self, out: list[str], span: Span, label: str, marker: str,
                        source_lines: dict[str, list[str]] | None) -> None:
        lines = (source_lines or {}).get(span.file)
        if lines and 1 <= span.line <= len(lines):
            src = lines[span.line - 1].rstrip("\n")
            gutter = str(span.line)
            pad = " " * len(gutter)
            out.append(f"{pad} |")
            out.append(f"{gutter} | {src}")
            width = max(1, (span.end_col or (span.col + 1)) - span.col)
            carets = " " * span.col + marker * width
            suffix = f" {label}" if label else ""
            out.append(f"{pad} | {carets}{suffix}")


class SerpError(Exception):
    """Raised to abort compilation with one or more diagnostics."""

    def __init__(self, diags: list[Diagnostic]):
        super().__init__(diags[0].message if diags else "compile error")
        self.diags = diags


@dataclass
class Reporter:
    """Collects diagnostics and source text for rendering."""

    diags: list[Diagnostic] = field(default_factory=list)
    sources: dict[str, list[str]] = field(default_factory=dict)

    def add_source(self, file: str, text: str) -> None:
        """Register a file's source text for diagnostic rendering."""
        self.sources[file] = text.splitlines()

    def error(self, code: str, name: str, message: str, span: Span, label: str = "",
              secondary: list | None = None, help: str = "") -> None:
        """Record one diagnostic."""
        self.diags.append(Diagnostic(code, name, message, span, label,
                                     secondary or [], help))

    def fatal(self, code: str, name: str, message: str, span: Span, label: str = "",
              secondary: list | None = None, help: str = "") -> None:
        """Record one diagnostic and abort compilation immediately."""
        self.error(code, name, message, span, label, secondary, help)
        raise SerpError(self.diags)

    def render_all(self) -> str:
        """Render every collected diagnostic, deduplicated and in source order."""
        seen = set()
        ordered = []
        for d in sorted(self.diags, key=lambda d: (d.span.file, d.span.line, d.span.col, d.code)):
            key = (d.code, d.span.file, d.span.line, d.span.col, d.message)
            if key not in seen:
                seen.add(key)
                ordered.append(d)
        return "\n\n".join(d.render(self.sources) for d in ordered)
