# serp-csv

CSV reader/writer written in the Serpentine subset, following RFC 4180.

## API

- `parse(text) -> list[list[str]]` — handles quoted fields, embedded commas,
  doubled-quote escapes, newlines inside quotes, LF / CRLF records; raises
  `ValueError` on an unterminated quote.
- `parse_line(line) -> list[str]` — first record only.
- `format_field(s)` / `needs_quoting(s)` — QUOTE_MINIMAL-style quoting.
- `format_row(list[str]) -> str` — one record, no terminator.
- `format_rows(list[list[str]]) -> str` — CRLF-terminated records (matches
  CPython csv's default lineterminator).

## Install

```
serp add serp-csv
pip install serp-csv
```
