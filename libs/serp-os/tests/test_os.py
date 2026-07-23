from serp_os import (getenv, putenv, unsetenv, getcwd, chdir, mkdir, rmdir,
                     remove, unlink, listdir)
from serp_os_core import exists, is_file, is_dir, has_env


def show(v: str | None) -> str:
    if v is None:
        return "<none>"
    return v


def main() -> None:
    print(has_env("SERP_TEST_VAR_W2"), show(getenv("SERP_TEST_VAR_W2")))
    print(show(getenv("SERP_TEST_VAR_W2", "fallback")))
    putenv("SERP_TEST_VAR_W2", "hello world")
    print(has_env("SERP_TEST_VAR_W2"), show(getenv("SERP_TEST_VAR_W2")))
    print(show(getenv("SERP_TEST_VAR_W2", "fallback")))
    unsetenv("SERP_TEST_VAR_W2")
    print(has_env("SERP_TEST_VAR_W2"))
    try:
        putenv("BAD=NAME", "x")
    except ValueError as e:
        print("caught:", e)
    try:
        putenv("", "x")
    except ValueError as e:
        print("caught:", e)

    cwd: str = getcwd()
    print(len(cwd) > 0)

    base: str = "tmp_serp_os_w2"
    if is_dir(base):
        stale: list[str] = listdir(base)
        for name in stale:
            remove(base + "/" + name)
        rmdir(base)
    print(exists(base), is_dir(base), is_file(base))
    mkdir(base)
    print(exists(base), is_dir(base), is_file(base))
    try:
        mkdir(base)
    except OSError as e:
        print("caught:", e)

    fa = open(base + "/a.txt", "w")
    na: int = fa.write("alpha")
    fa.close()
    fb = open(base + "/b.txt", "w")
    nb: int = fb.write("beta")
    fb.close()
    print(na, nb)
    print(listdir(base))
    print(is_file(base + "/a.txt"), is_dir(base + "/a.txt"))

    chdir(base)
    inner: str = getcwd()
    print(len(inner) > len(cwd))
    chdir(cwd)
    print(getcwd() == cwd)

    try:
        rmdir(base)
    except OSError as e:
        print("caught:", e)
    remove(base + "/a.txt")
    unlink(base + "/b.txt")
    try:
        remove(base + "/a.txt")
    except FileNotFoundError as e:
        print("caught:", e)
    print(listdir(base))
    rmdir(base)
    print(exists(base))
    try:
        seen: list[str] = listdir(base)
        print(seen)
    except FileNotFoundError as e:
        print("caught:", e)
    try:
        chdir(base)
    except FileNotFoundError as e:
        print("caught:", e)
    try:
        rmdir(base)
    except FileNotFoundError as e:
        print("caught:", e)


if __name__ == "__main__":
    main()
