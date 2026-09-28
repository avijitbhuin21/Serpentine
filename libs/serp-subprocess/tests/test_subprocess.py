"""serp-subprocess differential test: identical output under CPython and native builds."""
from __future__ import annotations
from serpentine import Ref
from serp_subprocess import run, check_output, check_call, call, Popen, CompletedProcess
from serp_subprocess import CalledProcessError, TimeoutExpired, PIPE, STDOUT, DEVNULL
from serp_os_core import getenv, has_env


def find_python() -> str:
    """Pick an interpreter name that launches on this machine."""
    for cand in ["python", "python3"]:
        try:
            r: CompletedProcess = run([cand, "-c", "print(1)"], capture_output=True)
            if r.returncode == 0:
                return cand
        except FileNotFoundError:
            pass
    return "python"


def show(r: Ref[CompletedProcess]) -> None:
    """Print a CompletedProcess and its fields."""
    print(r)
    print(" rc:", r.returncode, "out:", f"{r.stdout!r}", "err:", f"{r.stderr!r}")


def main() -> None:
    py: str = find_python()

    print("--- run: capture text")
    show(run([py, "-c", "print('hello')"], capture_output=True, text=True))

    print("--- run: capture bytes, stderr, exit code")
    r = run([py, "-c", "import sys; sys.stderr.write('oops'); sys.exit(3)"], capture_output=True)
    print(r.returncode, f"{r.stdout!r}", f"{r.stderr!r}")

    print("--- run: no capture")
    r2 = run([py, "-c", "import sys; sys.stderr.write('direct\\n')"])
    print(r2)

    print("--- run: check=True")
    try:
        run([py, "-c", "raise SystemExit(2)"], check=True)
    except CalledProcessError as e:
        print("CalledProcessError:", e)
    r3 = run([py, "-c", "raise SystemExit(7)"])
    try:
        r3.check_returncode()
    except CalledProcessError as e:
        print("check_returncode:", e)
    run([py, "-c", "pass"]).check_returncode()
    print("zero ok")

    print("--- run: input piping")
    r4 = run([py, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
             input="abc def\n", capture_output=True, text=True)
    print(f"{r4.stdout!r}")
    r5 = run([py, "-c", "import sys; d = sys.stdin.buffer.read(); sys.stdout.buffer.write(d[::-1])"],
             input=b"\x00\x01xyz", stdout=PIPE)
    print(f"{r5.stdout!r}", f"{r5.stderr!r}")

    print("--- run: stderr=STDOUT merge")
    r6 = run([py, "-c", "import sys; print('to-out'); sys.stdout.flush(); print('to-err', file=sys.stderr)"],
             stdout=PIPE, stderr=STDOUT, text=True)
    print(f"{r6.stdout!r}", f"{r6.stderr!r}")

    print("--- run: DEVNULL")
    r7 = run([py, "-c", "print('swallowed')"], stdout=DEVNULL, stderr=DEVNULL)
    print(r7)

    print("--- run: cwd")
    r8 = run([py, "-c", "import os; print(os.path.basename(os.getcwd()))"], cwd="..",
             capture_output=True, text=True)
    print(f"{r8.stdout!r}")

    print("--- run: env replacement")
    env: dict[str, str] = {"SERP_SP_X": "forty-two"}
    if has_env("SYSTEMROOT"):
        env["SYSTEMROOT"] = getenv("SYSTEMROOT")
    r9 = run([py, "-c", "import os; print(os.environ.get('SERP_SP_X'), 'SERP_SP_Y' in os.environ)"],
             env=env, capture_output=True, text=True)
    print(f"{r9.stdout!r}")

    print("--- run: shell=True")
    r10 = run("echo shell-hi", shell=True, capture_output=True, text=True)
    print(f"{r10.stdout!r}", r10.returncode)
    r11 = run("exit 5", shell=True)
    print(r11)

    print("--- run: missing program / empty args")
    try:
        run(["serp_definitely_missing_program_xyz", "--flag"])
    except FileNotFoundError as e:
        print("FileNotFoundError:", e)
    try:
        run([])
    except IndexError as e:
        print("IndexError:", e)
    try:
        run([py], input="x", stdin=PIPE)
    except ValueError as e:
        print("ValueError:", e)
    try:
        run([py], capture_output=True, stdout=PIPE)
    except ValueError as e:
        print("ValueError:", e)

    print("--- run: timeout")
    try:
        run([py, "-c", "import time; time.sleep(10)"], timeout=0.5, capture_output=True)
    except TimeoutExpired as e:
        print("TimeoutExpired:", e)

    print("--- check_output / call / check_call")
    out = check_output([py, "-c", "print('co')"], text=True)
    print(f"{out!r}")
    outb = check_output([py, "-c", "import sys; sys.stdout.buffer.write(b'raw')"])
    print(f"{outb!r}")
    try:
        check_output([py, "-c", "raise SystemExit(4)"])
    except CalledProcessError as e:
        print("CalledProcessError:", e)
    print(call([py, "-c", "raise SystemExit(9)"]))
    print(check_call([py, "-c", "pass"]))
    try:
        check_call([py, "-c", "raise SystemExit(1)"])
    except CalledProcessError as e:
        print("CalledProcessError:", e)

    print("--- Popen")
    p: Popen = Popen([py, "-c", "import sys; print('popen'); sys.stderr.write('e')"],
                     stdout=PIPE, stderr=PIPE, text=True)
    print(p.pid > 0, p.returncode)
    res = p.communicate()
    print(f"{res[0]!r}", f"{res[1]!r}", p.returncode, p.poll())

    p2: Popen = Popen([py, "-c", "import sys; sys.stdout.write(sys.stdin.read()[::-1])"],
                      stdin=PIPE, stdout=PIPE)
    res2 = p2.communicate(b"abc")
    print(f"{res2[0]!r}", res2[1], p2.returncode)

    p3: Popen = Popen([py, "-c", "raise SystemExit(6)"])
    print(p3.wait(), p3.returncode, p3.poll())

    p4: Popen = Popen([py, "-c", "import time; time.sleep(10)"])
    try:
        p4.wait(0.3)
    except TimeoutExpired as e:
        print("TimeoutExpired:", e)
    print(p4.poll())
    p4.kill()
    code: int = p4.wait()
    print(code != 0, p4.returncode == code)

    with Popen([py, "-c", "print('ctx')"], stdout=PIPE, text=True) as p5:
        r5b = p5.communicate()
        print(f"{r5b[0]!r}")
    print(p5.returncode)

    print("--- repr")
    print(CompletedProcess(["a", "b"], 1, None, None))
    print(CompletedProcess("a b", 0, "x", b"y"))
    print("done")


if __name__ == "__main__":
    main()
