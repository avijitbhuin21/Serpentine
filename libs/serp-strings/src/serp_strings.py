"""serp-strings — drop-in `textwrap` facade plus padding helpers in the Serpentine subset.

Pure Serpentine ([P]): the same source compiles natively with `serp` and
imports under CPython. wrap/fill/shorten/dedent/indent reimplement CPython
textwrap's TextWrapper algorithm faithfully (word splitting incl. hyphenated
words and em-dashes, sentence-ending detection, long-word breaking,
max_lines/placeholder truncation). Divergences: word-character classification
is ASCII-based (non-ASCII chars are treated as letters); indent() takes no
predicate; wrap() accepts its options positionally too (CPython's are
keyword-only past width).
"""
from __future__ import annotations
from serpentine import Ref, Mut


def repeat_char(ch: str, n: int) -> str:
    out: list[str] = []
    i: int = 0
    while i < n:
        out.append(ch)
        i += 1
    return "".join(out)


def ljust(s: str, width: int, fill_char: str = " ") -> str:
    if len(s) >= width:
        return s
    return s + repeat_char(fill_char, width - len(s))


def rjust(s: str, width: int, fill_char: str = " ") -> str:
    if len(s) >= width:
        return s
    return repeat_char(fill_char, width - len(s)) + s


def center(s: str, width: int, fill_char: str = " ") -> str:
    if len(s) >= width:
        return s
    margin: int = width - len(s)
    left: int = margin // 2
    return repeat_char(fill_char, left) + s + repeat_char(fill_char, margin - left)


def expandtabs(s: str, tabsize: int = 8) -> str:
    out: list[str] = []
    col: int = 0
    for i in range(len(s)):
        c: str = s[i]
        if c == "\t":
            if tabsize > 0:
                pad: int = tabsize - (col % tabsize)
                out.append(repeat_char(" ", pad))
                col += pad
        elif c == "\n" or c == "\r":
            out.append(c)
            col = 0
        else:
            out.append(c)
            col += 1
    return "".join(out)


def _is_line_break(c: str) -> bool:
    """Return whether c is a str.splitlines() line boundary character."""
    return (c == "\n" or c == "\r" or c == "\x0b" or c == "\x0c" or
            c == "\x1c" or c == "\x1d" or c == "\x1e" or c == "\x85" or
            c == "\u2028" or c == "\u2029")


def _splitlines_keepends(text: str) -> list[str]:
    """Split text like str.splitlines(keepends=True)."""
    out: list[str] = []
    i: int = 0
    n: int = len(text)
    start: int = 0
    while i < n:
        c: str = text[i]
        if c == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
            else:
                i += 1
            out.append(text[start:i])
            start = i
        elif _is_line_break(c):
            i += 1
            out.append(text[start:i])
            start = i
        else:
            i += 1
    if start < n:
        out.append(text[start:n])
    return out


def indent(text: str, prefix: str) -> str:
    """Add prefix to every non-whitespace-only line of text (textwrap.indent)."""
    out: list[str] = []
    for line in _splitlines_keepends(text):
        if line.strip() == "":
            out.append(line)
        else:
            out.append(prefix + line)
    return "".join(out)


def _only_space_tab(line: str) -> bool:
    """Return whether a non-empty line consists solely of spaces and tabs."""
    if line == "":
        return False
    for c in line:
        if c != " " and c != "\t":
            return False
    return True


def dedent(text: str) -> str:
    """Remove the common leading whitespace from all lines (textwrap.dedent)."""
    lines: list[str] = text.split("\n")
    blanked: list[str] = []
    for line in lines:
        if _only_space_tab(line):
            blanked.append("")
        else:
            blanked.append(line)
    margin: str = ""
    have_margin: bool = False
    for line1 in blanked:
        if line1 == "":
            continue
        k: int = 0
        while k < len(line1) and (line1[k] == " " or line1[k] == "\t"):
            k += 1
        lead: str = line1[:k]
        if not have_margin:
            margin = lead
            have_margin = True
        else:
            common: int = 0
            limit: int = min(len(margin), len(lead))
            for j2 in range(limit):
                if margin[j2] == lead[j2]:
                    common += 1
                else:
                    break
            margin = margin[:common]
    out: list[str] = []
    for line2 in blanked:
        if margin != "" and line2.startswith(margin):
            out.append(line2[len(margin):])
        else:
            out.append(line2)
    return "\n".join(out)


def _is_space(c: str) -> bool:
    """Return whether c is one of textwrap's whitespace characters."""
    return c == " " or c == "\t" or c == "\n" or c == "\x0b" or c == "\x0c" or c == "\r"


def _is_word(c: str) -> bool:
    """ASCII approximation of regex \\w (non-ASCII counts as a letter)."""
    if c >= "a" and c <= "z":
        return True
    if c >= "A" and c <= "Z":
        return True
    if c >= "0" and c <= "9":
        return True
    if c == "_":
        return True
    return c >= "\x80"


def _is_letter(c: str) -> bool:
    """ASCII approximation of regex [^\\d\\W] (word char that is not a digit)."""
    if c >= "0" and c <= "9":
        return False
    return _is_word(c)


def _is_lower(c: str) -> bool:
    """Return whether c is an ASCII lowercase letter (regex [a-z])."""
    return c >= "a" and c <= "z"


def _is_word_punct(c: str) -> bool:
    """Return whether c matches textwrap's em-dash lookbehind class [\\w!\"'&.,?]."""
    if _is_word(c):
        return True
    return (c == "!" or c == '"' or c == "'" or c == "&" or c == "." or
            c == "," or c == "?")


def _munge_whitespace(text: str, expand: bool, replace: bool, tabsize: int) -> str:
    """Expand tabs and normalize whitespace to spaces, like TextWrapper._munge_whitespace."""
    out: str = text
    if expand:
        out = expandtabs(out, tabsize)
    if replace:
        result: list[str] = []
        for i in range(len(out)):
            c: str = out[i]
            if _is_space(c):
                result.append(" ")
            else:
                result.append(c)
        return "".join(result)
    return out


def _split_simple(text: str) -> list[str]:
    """Split text into alternating whitespace/non-whitespace chunks (wordsep_simple_re)."""
    chunks: list[str] = []
    i: int = 0
    n: int = len(text)
    while i < n:
        j: int = i
        if _is_space(text[i]):
            while j < n and _is_space(text[j]):
                j += 1
        else:
            while j < n and not _is_space(text[j]):
                j += 1
        chunks.append(text[i:j])
        i = j
    return chunks


def _hyphen_break_ok(text: str, start: int, j: int) -> bool:
    """Return whether j is a valid hyphenated-word break (wordsep_re alternative 1)."""
    n: int = len(text)
    if j < start + 2 or text[j - 1] != "-":
        return False
    ok_behind: bool = False
    if j >= 3 and _is_letter(text[j - 3]) and _is_letter(text[j - 2]):
        ok_behind = True
    if not ok_behind and j >= 4 and _is_lower(text[j - 4]) and text[j - 3] == "-" \
            and _is_lower(text[j - 2]):
        ok_behind = True
    if not ok_behind:
        return False
    if j >= n or not _is_letter(text[j]):
        return False
    if j + 1 < n and _is_letter(text[j + 1]):
        return True
    if j + 2 < n and text[j + 1] == "-" and _is_letter(text[j + 2]):
        return True
    return False


def _emdash_break_ok(text: str, j: int) -> bool:
    """Return whether j is an em-dash word boundary (wordsep_re alternative 3c)."""
    n: int = len(text)
    if not _is_word_punct(text[j - 1]):
        return False
    if j + 1 >= n or text[j] != "-" or text[j + 1] != "-":
        return False
    k: int = j
    while k < n and text[k] == "-":
        k += 1
    return k < n and _is_word(text[k])


def _split_hyphen(text: str) -> list[str]:
    """Split text into chunks like textwrap's wordsep_re (break_on_hyphens=True)."""
    chunks: list[str] = []
    i: int = 0
    n: int = len(text)
    while i < n:
        c: str = text[i]
        if _is_space(c):
            j: int = i
            while j < n and _is_space(text[j]):
                j += 1
            chunks.append(text[i:j])
            i = j
            continue
        if c == "-" and i > 0 and _is_word_punct(text[i - 1]):
            k: int = i
            while k < n and text[k] == "-":
                k += 1
            if k - i >= 2 and k < n and _is_word(text[k]):
                chunks.append(text[i:k])
                i = k
                continue
        end: int = n
        j2: int = i + 1
        while j2 < n:
            if _is_space(text[j2]):
                end = j2
                break
            if _hyphen_break_ok(text, i, j2):
                end = j2
                break
            if _emdash_break_ok(text, j2):
                end = j2
                break
            j2 += 1
        chunks.append(text[i:end])
        i = end
    return chunks


def _ends_sentence(chunk: str) -> bool:
    """Return whether chunk ends like a sentence (regex [a-z][.!?][\"']?\\Z)."""
    k: int = len(chunk) - 1
    if k >= 0 and (chunk[k] == '"' or chunk[k] == "'"):
        k -= 1
    if k < 1:
        return False
    c: str = chunk[k]
    if c != "." and c != "!" and c != "?":
        return False
    return _is_lower(chunk[k - 1])


def _fix_sentence_endings(chunks: Mut[list[str]]) -> None:
    """Ensure two spaces after sentence-ending chunks, like TextWrapper."""
    i: int = 0
    while i < len(chunks) - 1:
        if chunks[i + 1] == " " and _ends_sentence(chunks[i]):
            chunks[i + 1] = "  "
            i += 2
        else:
            i += 1


def _handle_long_word(chunks: Mut[list[str]], cur_line: Mut[list[str]], cur_len: int,
                      w: int, break_long_words: bool, break_on_hyphens: bool) -> None:
    """Break a too-long word onto the current line, like TextWrapper._handle_long_word."""
    space_left: int = 1 if w < 1 else w - cur_len
    if break_long_words:
        chunk: str = chunks[len(chunks) - 1]
        end: int = space_left
        if break_on_hyphens and len(chunk) > space_left:
            hyphen: int = -1
            hi: int = space_left - 1
            while hi >= 0:
                if chunk[hi] == "-":
                    hyphen = hi
                    break
                hi -= 1
            if hyphen > 0:
                has_non_hyphen: bool = False
                for ci in range(hyphen):
                    if chunk[ci] != "-":
                        has_non_hyphen = True
                        break
                if has_non_hyphen:
                    end = hyphen + 1
        cur_line.append(chunk[:end])
        chunks[len(chunks) - 1] = chunk[end:]
    elif len(cur_line) == 0:
        cur_line.append(chunks.pop())


def _wrap_chunks(chunks: Mut[list[str]], width: int, initial_indent: str,
                 subsequent_indent: str, drop_whitespace: bool, break_long_words: bool,
                 break_on_hyphens: bool, has_max: bool, max_lines: int,
                 placeholder: str) -> list[str]:
    """Assemble chunks into wrapped lines, like TextWrapper._wrap_chunks."""
    lines: list[str] = []
    if width <= 0:
        raise ValueError(f"invalid width {width} (must be > 0)")
    if has_max:
        indent0: str = subsequent_indent if max_lines > 1 else initial_indent
        if len(indent0) + len(placeholder.lstrip()) > width:
            raise ValueError("placeholder too large for max width")
    chunks.reverse()
    while len(chunks) > 0:
        cur_line: list[str] = []
        cur_len: int = 0
        line_indent: str = subsequent_indent if len(lines) > 0 else initial_indent
        w: int = width - len(line_indent)
        if drop_whitespace and len(lines) > 0 and chunks[len(chunks) - 1].strip() == "":
            chunks.pop()
        while len(chunks) > 0:
            l: int = len(chunks[len(chunks) - 1])
            if cur_len + l <= w:
                cur_line.append(chunks.pop())
                cur_len += l
            else:
                break
        if len(chunks) > 0 and len(chunks[len(chunks) - 1]) > w:
            _handle_long_word(chunks, cur_line, cur_len, w,
                              break_long_words, break_on_hyphens)
            cur_len = 0
            for piece in cur_line:
                cur_len += len(piece)
        if drop_whitespace and len(cur_line) > 0 \
                and cur_line[len(cur_line) - 1].strip() == "":
            cur_len -= len(cur_line[len(cur_line) - 1])
            cur_line.pop()
        if len(cur_line) > 0:
            take: bool = False
            if not has_max:
                take = True
            elif len(lines) + 1 < max_lines:
                take = True
            elif (len(chunks) == 0 or (drop_whitespace and len(chunks) == 1
                                       and chunks[0].strip() == "")) and cur_len <= w:
                take = True
            if take:
                lines.append(line_indent + "".join(cur_line))
            else:
                handled: bool = False
                while len(cur_line) > 0:
                    last: str = cur_line[len(cur_line) - 1]
                    if last.strip() != "" and cur_len + len(placeholder) <= w:
                        cur_line.append(placeholder)
                        lines.append(line_indent + "".join(cur_line))
                        handled = True
                        break
                    cur_len -= len(last)
                    cur_line.pop()
                if not handled:
                    if len(lines) > 0:
                        last_i: int = len(lines) - 1
                        prev_line: str = lines[last_i].rstrip()
                        if len(prev_line) + len(placeholder) <= width:
                            lines[last_i] = prev_line + placeholder
                            handled = True
                    if not handled:
                        lines.append(line_indent + placeholder.lstrip())
                break
    return lines


def wrap(text: str, width: int = 70, initial_indent: str = "",
         subsequent_indent: str = "", expand_tabs: bool = True,
         replace_whitespace: bool = True, fix_sentence_endings: bool = False,
         break_long_words: bool = True, drop_whitespace: bool = True,
         break_on_hyphens: bool = True, tabsize: int = 8,
         max_lines: int | None = None, placeholder: str = " [...]") -> list[str]:
    """Wrap text into a list of lines at most `width` columns wide (textwrap.wrap)."""
    munged: str = _munge_whitespace(text, expand_tabs, replace_whitespace, tabsize)
    chunks: list[str] = []
    if break_on_hyphens:
        chunks = _split_hyphen(munged)
    else:
        chunks = _split_simple(munged)
    if fix_sentence_endings:
        _fix_sentence_endings(chunks)
    has_max: bool = False
    ml: int = 0
    if max_lines is not None:
        has_max = True
        ml = max_lines
    return _wrap_chunks(chunks, width, initial_indent, subsequent_indent,
                        drop_whitespace, break_long_words, break_on_hyphens,
                        has_max, ml, placeholder)


def fill(text: str, width: int = 70, initial_indent: str = "",
         subsequent_indent: str = "", expand_tabs: bool = True,
         replace_whitespace: bool = True, fix_sentence_endings: bool = False,
         break_long_words: bool = True, drop_whitespace: bool = True,
         break_on_hyphens: bool = True, tabsize: int = 8,
         max_lines: int | None = None, placeholder: str = " [...]") -> str:
    """Wrap text and join the lines with newlines (textwrap.fill)."""
    return "\n".join(wrap(text, width, initial_indent, subsequent_indent,
                          expand_tabs, replace_whitespace, fix_sentence_endings,
                          break_long_words, drop_whitespace, break_on_hyphens,
                          tabsize, max_lines, placeholder))


def shorten(text: str, width: int, placeholder: str = " [...]") -> str:
    """Collapse whitespace and truncate text to fit in `width` (textwrap.shorten)."""
    collapsed: str = " ".join(text.strip().split())
    return fill(collapsed, width, "", "", True, True, False, True, True, True,
                8, 1, placeholder)
