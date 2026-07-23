"""serp-csv — CSV reader/writer with RFC 4180 quoting in the Serpentine subset.

Pure Serpentine ([P]). reader(lines) mirrors csv.reader over a list of input
lines (default dialect: comma, double-quote escaping, QUOTE_MINIMAL,
non-strict) but returns an eager list of rows instead of an iterator; quoted
fields may span lines, blank lines yield [] like CPython. writer() mirrors
csv.writer's writerow/writerows quoting exactly, but owns its output buffer
(getvalue()) because the ownership model forbids storing a borrowed file
object; fields are str-only. DictReader(lines) mirrors csv.DictReader eagerly
(list of dicts; missing fields get restval, extra fields are dropped — no
restkey since dict keys are str). parse()/format_rows() are the original
whole-text helpers.
"""
from __future__ import annotations
from serpentine import Ref, Mut, PyVal, dataclass, move


def parse(text: str) -> list[list[str]]:
    records: list[list[str]] = []
    field: list[str] = []
    row: list[str] = []
    in_quotes: bool = False
    started_row: bool = False
    i: int = 0
    n: int = len(text)
    while i < n:
        c: str = text[i]
        if in_quotes:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                else:
                    in_quotes = False
                    i += 1
            else:
                field.append(c)
                i += 1
        elif c == '"':
            in_quotes = True
            started_row = True
            i += 1
        elif c == ",":
            row.append("".join(field))
            field.clear()
            started_row = True
            i += 1
        elif c == "\r" or c == "\n":
            if started_row or len(field) > 0:
                row.append("".join(field))
                field.clear()
                records.append(move(row))
                row = []
                started_row = False
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 2
            else:
                i += 1
        else:
            field.append(c)
            started_row = True
            i += 1
    if in_quotes:
        raise ValueError("unterminated quoted field")
    if started_row or len(field) > 0:
        row.append("".join(field))
        records.append(move(row))
    return records


def parse_line(line: str) -> list[str]:
    rows: list[list[str]] = parse(line)
    if len(rows) == 0:
        empty: list[str] = []
        return empty
    return rows.pop(0)


def needs_quoting(field: str) -> bool:
    if field.find(",") >= 0 or field.find('"') >= 0:
        return True
    if field.find("\n") >= 0 or field.find("\r") >= 0:
        return True
    return False


def format_field(field: str) -> str:
    if not needs_quoting(field):
        return field
    return '"' + field.replace('"', '""') + '"'


def format_row(row: Ref[list[str]]) -> str:
    parts: list[str] = []
    for f in row:
        parts.append(format_field(f))
    return ",".join(parts)


def format_rows(rows: Ref[list[list[str]]]) -> str:
    out: list[str] = []
    for i in range(len(rows)):
        out.append(format_row(rows[i]))
        out.append("\r\n")
    return "".join(out)


class Error(Exception):
    pass


def reader(lines: Ref[list[str]]) -> list[list[str]]:
    """Parse CSV rows from input lines like csv.reader (eager list of rows)."""
    rows: list[list[str]] = []
    field: list[str] = []
    row: list[str] = []
    in_quotes: bool = False
    at_field_start: bool = True
    saw_char: bool = False
    for li in range(len(lines)):
        line: str = lines[li]
        n: int = len(line)
        i: int = 0
        row_ended: bool = False
        while i < n:
            c: str = line[i]
            if in_quotes:
                saw_char = True
                if c == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        field.append('"')
                        i += 2
                    else:
                        in_quotes = False
                        i += 1
                else:
                    field.append(c)
                    i += 1
            elif c == "\r" or c == "\n":
                if saw_char:
                    row.append("".join(field))
                    field.clear()
                for j in range(i + 1, n):
                    cj: str = line[j]
                    if cj != "\r" and cj != "\n":
                        raise Error("new-line character seen in unquoted field - "
                                    "do you need to open the file with newline=''?")
                row_ended = True
                i = n
            elif c == '"' and at_field_start:
                saw_char = True
                in_quotes = True
                at_field_start = False
                i += 1
            elif c == ",":
                saw_char = True
                row.append("".join(field))
                field.clear()
                at_field_start = True
                i += 1
            else:
                saw_char = True
                field.append(c)
                at_field_start = False
                i += 1
        if row_ended or not in_quotes:
            if not row_ended and saw_char:
                row.append("".join(field))
                field.clear()
            rows.append(move(row))
            row = []
            saw_char = False
            at_field_start = True
            in_quotes = False
    if in_quotes or saw_char or len(row) > 0:
        if saw_char:
            row.append("".join(field))
        rows.append(move(row))
    return rows


def DictReader(lines: Ref[list[str]], fieldnames: PyVal | None = None,
               restval: PyVal | None = None) -> PyVal:
    """Eager csv.DictReader: rows as dicts keyed by the header (or fieldnames)."""
    rows: list[list[str]] = reader(lines)
    names: list[str] = []
    start: int = 0
    if fieldnames is not None:
        for f in fieldnames:
            names.append(str(f))
    else:
        if len(rows) == 0:
            return []
        for cell in rows[start]:
            names.append(cell)
        start += 1
    out: list[PyVal] = []
    for ri in range(start, len(rows)):
        if len(rows[ri]) == 0:
            continue
        d: dict[str, PyVal] = {}
        for ci in range(len(names)):
            if ci < len(rows[ri]):
                d[names[ci]] = rows[ri][ci]
            elif restval is not None:
                d[names[ci]] = restval
            else:
                d[names[ci]] = None
        out.append(move(d))
    return out


@dataclass
class _Writer:
    chunks: list[str]

    def writerow(self: Mut[_Writer], row: Ref[list[str]]) -> None:
        if len(row) == 1 and row[0] == "":
            self.chunks.append('""\r\n')
            return
        self.chunks.append(format_row(row) + "\r\n")

    def writerows(self: Mut[_Writer], rows: Ref[list[list[str]]]) -> None:
        for i in range(len(rows)):
            self.writerow(rows[i])

    def getvalue(self: Ref[_Writer]) -> str:
        return "".join(self.chunks)


def writer() -> _Writer:
    """Create a buffer-owning CSV writer with csv.writer's quoting rules."""
    chunks: list[str] = []
    return _Writer(move(chunks))
