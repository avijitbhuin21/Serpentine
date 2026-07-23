from serp_pathlib import (join, parent, name, suffix, stem, with_suffix, parts,
                          is_absolute, exists, is_file, is_dir, mkdir, rmdir,
                          remove, listdir, Path)


def path_section() -> None:
    p: Path = Path("a/b/c.tar.gz")
    print(p.as_posix(), p.name, p.stem, p.suffix)
    print(p.parent.as_posix(), p.parts)
    print(p.is_absolute(), Path("/x").is_absolute())
    print(p)
    print(f"{p!r}", [p.parent, Path("x.txt")])
    print(str(p) == "a/b/c.tar.gz", f"path={p}")
    q: Path = p.parent / "other.txt"
    print(q.as_posix())
    print(p.joinpath("sub").as_posix())
    print(p.with_suffix(".zip").as_posix())
    print(p.with_name("renamed.md").as_posix())
    print(len(str(Path.cwd())) > 0, Path.cwd().is_dir())
    try:
        bad: Path = Path("/").with_name("x")
        print(bad.as_posix())
    except ValueError as e:
        print("caught:", e)
    print(Path("a/b") == Path("a/b"), Path("a/b") == Path("a/c"))

    base: Path = Path("tmp_serp_pathlib_obj")
    if base.is_dir():
        for child in base.iterdir():
            child.unlink()
        base.rmdir()
    base.mkdir()
    f1: Path = base / "one.txt"
    f2: Path = base / "two.bin"
    print(f1.write_text("hello path"))
    print(f2.write_bytes(b"\x01\x02\x03"))
    print(f1.read_text(), f2.read_bytes())
    print(f1.exists(), f1.is_file(), f1.is_dir())
    kids: list[Path] = base.iterdir()
    for k in kids:
        print(k.as_posix(), k.name, k.suffix)
    f1.unlink()
    f2.unlink()
    base.rmdir()
    print(base.exists())


def main() -> None:
    print(join("a", "b"), join("a/", "b"), join("a", ""), join("", "b"))
    print(join("a/b", "c/d"), join("a", "/abs"), join("C:/x", "y"))
    print(parent("a/b/c"), parent("a/b/"), parent("a"), parent("/a"), parent("/"))
    print(parent("C:/x/y"), parent("C:/"), parent("a\\b\\c"))
    print(name("a/b/c.txt"), name("a/b/"), name("/"), name("c.txt"))
    print(suffix("a/b.tar.gz"), suffix("a/b"), suffix("a/.bashrc"), suffix("x.py"))
    print(stem("a/b.tar.gz"), stem("a/b"), stem("a/.bashrc"))
    print(with_suffix("a/b.txt", ".md"), with_suffix("a/b", ".md"), with_suffix("a/b.txt", ""))
    try:
        print(with_suffix("a/b.txt", "md"))
    except ValueError as e:
        print("caught:", e)
    print(parts("a/b/c"), parts("/a/b"), parts("C:/x/y"), parts("a"))
    print(is_absolute("/a"), is_absolute("C:/a"), is_absolute("a/b"), is_absolute("\\net"))

    base: str = "tmp_serp_pathlib_w2"
    if is_dir(base):
        stale: list[str] = listdir(base)
        for f in stale:
            remove(join(base, f))
        rmdir(base)
    mkdir(base)
    target: str = join(base, "data.txt")
    fh = open(target, "w")
    n: int = fh.write("path data")
    fh.close()
    print(n, exists(target), is_file(target), is_dir(target))
    print(listdir(base))
    print(name(target), suffix(target), stem(target), parent(target))
    remove(target)
    rmdir(base)
    print(exists(base))
    path_section()


if __name__ == "__main__":
    main()
