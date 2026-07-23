# serp-log

A `logging` drop-in for the Serpentine subset. The process-global logger
registry and configuration live in the **runtime** (`serp_log_core`, a
str→str KV store + stderr sink — DECISIONS.md D12), so `getLogger("a.b")`
behaves like CPython's singleton registry even though `Logger` values are
plain immutable dataclasses.

## Mirrored surface (19/19 stdlib parity checks)

- `getLogger(name="")` with dotted-name effective-level inheritance;
  `setLevel / getEffectiveLevel / isEnabledFor / level`.
- `debug/info/warning/error/critical/log` on loggers and at module level
  (module-level calls run `basicConfig()` implicitly, like CPython).
- `basicConfig(level=, format=, filename=, filemode=)` with CPython's
  configure-once semantics; file output is byte-identical to stdlib.
- The last-resort handler: unconfigured records ≥ WARNING print the bare
  message to stderr.
- `getLevelName` incl. the `"Level N"` form; constants
  `CRITICAL/FATAL/ERROR/WARNING/WARN/INFO/DEBUG/NOTSET`.

## Caps

Messages are single pre-formatted strings (use f-strings — no `%`-args);
`format` supports `%(levelname)s/%(name)s/%(message)s`; no
Handler/Formatter/Filter objects; no `exception()`/`exc_info`; no
`addLevelName`/`disable`. Legacy helpers (`make_logger`, `log_line`,
`level_name`, `append_log`) are retained.

Install into a Serpentine project with `serp add serp-log`.
