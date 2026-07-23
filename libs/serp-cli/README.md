# serp-cli

An argparse-lite command-line parser written in the Serpentine subset —
native CLIs are Serpentine's first market.

## API

```python
cli = new_cli("mytool", "Does things.")
cli.add_command("build")        # optional subcommands (first positional)
cli.add_flag("verbose", "chatty output")
cli.add_opt("out", "a.out", "output path")   # --out value or --out=value
cli.add_pos("input", "input file")
res = cli.parse(argv)           # ParseResult
```

`ParseResult` fields: `ok` / `error` (parse failure, message), `help_requested`
(`-h` / `--help` seen; caller prints `cli.usage()` and exits), `command`,
`flags: dict[str, bool]`, `opts: dict[str, str]`, `pos: dict[str, str]`,
`extras: list[str]` (surplus positionals).

## Install

```
serp add serp-cli
pip install serp-cli
```
