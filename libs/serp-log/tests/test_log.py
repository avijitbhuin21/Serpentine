from serp_log import (CRITICAL, DEBUG, ERROR, INFO, WARNING, Logger, append_log,
                      basicConfig, getLevelName, getLogger, info, level_name, log,
                      log_line, make_logger, warning)
from serp_os_core import exists, remove


def main() -> None:
    print(getLevelName(50), getLevelName(40), getLevelName(30), getLevelName(20))
    print(getLevelName(10), getLevelName(0), getLevelName(35))
    root: Logger = getLogger()
    print(root.name, root.level, root.getEffectiveLevel())
    a: Logger = getLogger("app")
    ab: Logger = getLogger("app.db")
    print(a.name, ab.name, a.level, ab.getEffectiveLevel())
    print(a.isEnabledFor(INFO), a.isEnabledFor(WARNING))
    ab.debug("dropped: below last-resort threshold")
    ab.warning("last-resort line on stderr")
    path: str = "tmp_serp_log_obj.txt"
    if exists(path):
        remove(path)
    basicConfig(level=DEBUG, filename=path, filemode="w")
    basicConfig(level=CRITICAL)
    print(root.getEffectiveLevel())
    a.setLevel(WARNING)
    print(a.getEffectiveLevel(), ab.getEffectiveLevel(), root.getEffectiveLevel())
    ab.info("filtered: inherits WARNING from app")
    ab.error("db down")
    a.warning("disk low")
    getLogger("other").debug("debug visible via root DEBUG")
    root.critical("boom")
    log(35, "custom level record")
    info("root info")
    warning("root warning")
    ab.setLevel(DEBUG)
    print(ab.level, ab.getEffectiveLevel())
    ab.debug("now visible")
    lg: Logger = make_logger("legacy", ERROR)
    print(lg.getEffectiveLevel())
    lg.warning("hidden by legacy level")
    lg.error("legacy error")
    append_log(path, "raw appended line")
    with open(path, "r") as f:
        text: str = f.read()
    print("----")
    print(text)
    remove(path)
    print(exists(path))
    print(level_name(45), level_name(30), level_name(20), level_name(5))
    print(log_line("app", ERROR, "x"))


if __name__ == "__main__":
    main()
