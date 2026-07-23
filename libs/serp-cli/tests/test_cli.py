from serpentine import PyVal, Ref
from serp_cli import ArgumentParser, Cli, ParseResult, new_cli


def argparse_section() -> None:
    ap: ArgumentParser = ArgumentParser(prog="snaketool", description="A demo Serpentine CLI.")
    ap.add_argument("-v", "--verbose", action="store_true", help="chatty output")
    ap.add_argument("--out", default="a.out", help="output path")
    ap.add_argument("-n", "--dry-run", action="store_true", help="no writes")
    ap.add_argument("input", help="input file")
    a1: PyVal = ap.parse_args(["main.py", "--verbose", "--out", "prog.exe"])
    print(a1)
    print(a1["verbose"], str(a1["out"]), str(a1["input"]))
    a2: PyVal = ap.parse_args(["--out=fast.exe", "x.py", "-n"])
    print(a2)
    print(a2["dry_run"], a2["verbose"])
    a3: PyVal = ap.parse_args(["-v", "y.py"])
    print(a3["verbose"], str(a3["input"]))
    if a3["verbose"]:
        print("verbose on")
    plain: ArgumentParser = ArgumentParser(prog="greet")
    plain.add_argument("name", help="who to greet")
    a4: PyVal = plain.parse_args(["world"])
    print(a4)
    print("----")
    print(ap.format_usage())
    print("----")
    print(ap.format_help())
    print("----")
    print(plain.format_help())


def show(res: Ref[ParseResult]) -> None:
    print(res.ok, res.error, res.help_requested, res.command)
    print(res.flags)
    print(res.opts)
    print(res.pos)
    print(res.extras)


def main() -> None:
    cli: Cli = new_cli("snaketool", "A demo Serpentine CLI.")
    cli.add_command("build")
    cli.add_command("run")
    cli.add_flag("verbose", "chatty output")
    cli.add_flag("debug", "keep debug info")
    cli.add_opt("out", "a.out", "output path")
    cli.add_pos("input", "input file")

    args1: list[str] = ["build", "main.py", "--verbose", "--out", "prog.exe"]
    show(cli.parse(args1))
    args2: list[str] = ["run", "main.py", "--out=fast.exe", "extra1", "extra2"]
    show(cli.parse(args2))
    args3: list[str] = ["-h"]
    show(cli.parse(args3))
    bad1: list[str] = ["fly", "x.py"]
    show(cli.parse(bad1))
    bad2: list[str] = ["build"]
    show(cli.parse(bad2))
    bad3: list[str] = ["build", "x.py", "--nope"]
    show(cli.parse(bad3))
    bad4: list[str] = ["build", "x.py", "--out"]
    show(cli.parse(bad4))
    bad5: list[str] = ["build", "x.py", "--verbose=1"]
    show(cli.parse(bad5))
    bad6: list[str] = []
    show(cli.parse(bad6))
    print("----")
    print(cli.usage())

    plain: Cli = new_cli("greet", "")
    plain.add_pos("name", "who to greet")
    args7: list[str] = ["world"]
    show(plain.parse(args7))
    print("----")
    print(plain.usage())
    print("====")
    argparse_section()


if __name__ == "__main__":
    main()
