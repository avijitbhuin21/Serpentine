"""serp-prometheus — prometheus_client-style metrics for Serpentine services.

`Counter`, `Gauge`, `Histogram` and `Summary` with label children (`.labels(...)`),
`inc/dec/set/observe`, and `generate_latest()` producing the Prometheus text
exposition format (version 0.0.4, `CONTENT_TYPE_LATEST`). Metric objects may be
module-level (`REQUESTS = Counter(...)`): their values live in a process-global
runtime store, so every worker thread reports into the same registry and a Venom
`/metrics` route can serve `generate_latest()`.

Families print in registration order and children in creation order, with
prometheus_client's naming (`*_total` counters, `*_bucket{le=...}`/`_count`/`_sum`).

Caps: one global registry (no CollectorRegistry/`registry=`); no `*_created`
samples or process/platform collectors; `labels()` takes up to four positional
values (no keyword form); no `Info`/`Enum`, `time()` decorators or exporters
(`start_http_server`): mount `generate_latest()` on a route instead.
"""
from __future__ import annotations
from serpentine import Mut, Ref, dataclass, move
from serp_metrics_core import mx_add, mx_set, mx_get, mx_meta_set, mx_meta_get, mx_meta_add

CONTENT_TYPE_LATEST: str = "text/plain; version=0.0.4; charset=utf-8"


def _fmt(v: float) -> str:
    """Prometheus float text (Go style for infinities and NaN)."""
    if v != v:
        return "NaN"
    if v > 1.7976931348623157e308:
        return "+Inf"
    if v < -1.7976931348623157e308:
        return "-Inf"
    return str(v)


def _escape_label(v: str) -> str:
    """Escape a label value for the text format."""
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")


def _escape_help(v: str) -> str:
    """Escape HELP text for the text format."""
    return v.replace("\\", "\\\\").replace("\n", "\\n")


def _split(text: str) -> list[str]:
    """Items of a newline-separated metadata list (the store prefixes every item with '\\n')."""
    out: list[str] = []
    if text == "":
        return out
    for item in text[1:len(text)].split("\n"):
        out.append(item)
    return out


def _register(name: str, kind: str, doc: str, labelnames: Ref[list[str]]) -> None:
    """Record a metric family once; re-registering the same family is a no-op."""
    prev: str = mx_meta_get("type:" + name)
    if prev != "":
        if prev != kind:
            raise ValueError(f"Duplicated timeseries in CollectorRegistry: {{'{name}'}}")
        return
    mx_meta_set("type:" + name, kind)
    mx_meta_set("help:" + name, doc)
    mx_meta_set("labels:" + name, ",".join(labelnames))
    added: bool = mx_meta_add("families", name)


def _child_key(name: str, labelnames: Ref[list[str]], v1: str, v2: str, v3: str, v4: str) -> str:
    """Validate label values and build the `{a="x",b="y"}` key for one child."""
    given: list[str] = [v1, v2, v3, v4]
    n: int = 0
    for g in given:
        if g != "":
            n += 1
    if n != len(labelnames):
        raise ValueError("Incorrect label count")
    parts: list[str] = []
    i: int = 0
    while i < len(labelnames):
        parts.append(labelnames[i] + "=\"" + _escape_label(given[i]) + "\"")
        i += 1
    key: str = "{" + ",".join(parts) + "}"
    added: bool = mx_meta_add("children:" + name, key)
    return key


def _strip_suffix(name: str, suffix: str) -> str:
    """Drop a trailing suffix (prometheus_client strips `_total` from counter names)."""
    if name.endswith(suffix):
        return name[0:len(name) - len(suffix)]
    return name


def _copy_names(names: Ref[list[str]]) -> list[str]:
    """An owned copy of a label-name list."""
    out: list[str] = []
    for n in names:
        out.append(n)
    return out


def _check_parent(labelnames: Ref[list[str]], key: str, kind: str) -> None:
    """A labelled metric must be used through .labels(...)."""
    if len(labelnames) > 0 and key == "":
        raise ValueError(f"{kind} metric is missing label values")


@dataclass
class Counter:
    name: str
    documentation: str
    labelnames: list[str] = []
    _key: str = ""

    def __post_init__(self: Mut[Counter]) -> None:
        self.name = _strip_suffix(self.name, "_total")
        _register(self.name, "counter", self.documentation, self.labelnames)
        if len(self.labelnames) == 0:
            added: bool = mx_meta_add("children:" + self.name, "")

    def labels(self: Ref[Counter], v1: str = "", v2: str = "", v3: str = "", v4: str = "") -> Counter:
        key: str = _child_key(self.name, self.labelnames, v1, v2, v3, v4)
        return Counter(self.name, self.documentation, _copy_names(self.labelnames), key)

    def inc(self: Ref[Counter], amount: float = 1.0) -> None:
        _check_parent(self.labelnames, self._key, "counter")
        if amount < 0.0:
            raise ValueError("Counters can only be incremented by non-negative amounts.")
        mx_add(self.name + "_total" + self._key, amount)

    def get(self: Ref[Counter]) -> float:
        """Current value (serp extension; prometheus_client reads via collect())."""
        return mx_get(self.name + "_total" + self._key)


@dataclass
class Gauge:
    name: str
    documentation: str
    labelnames: list[str] = []
    _key: str = ""

    def __post_init__(self: Mut[Gauge]) -> None:
        _register(self.name, "gauge", self.documentation, self.labelnames)
        if len(self.labelnames) == 0:
            added: bool = mx_meta_add("children:" + self.name, "")

    def labels(self: Ref[Gauge], v1: str = "", v2: str = "", v3: str = "", v4: str = "") -> Gauge:
        key: str = _child_key(self.name, self.labelnames, v1, v2, v3, v4)
        return Gauge(self.name, self.documentation, _copy_names(self.labelnames), key)

    def inc(self: Ref[Gauge], amount: float = 1.0) -> None:
        _check_parent(self.labelnames, self._key, "gauge")
        mx_add(self.name + self._key, amount)

    def dec(self: Ref[Gauge], amount: float = 1.0) -> None:
        _check_parent(self.labelnames, self._key, "gauge")
        mx_add(self.name + self._key, -amount)

    def set(self: Ref[Gauge], value: float) -> None:
        _check_parent(self.labelnames, self._key, "gauge")
        mx_set(self.name + self._key, value)

    def get(self: Ref[Gauge]) -> float:
        """Current value (serp extension)."""
        return mx_get(self.name + self._key)


def _bucket_bounds(name: str) -> list[float]:
    """The finite upper bounds stored for a histogram family."""
    out: list[float] = []
    text: str = mx_meta_get("buckets:" + name)
    if text == "":
        return out
    for b in text.split(","):
        out.append(float(b))
    return out


def _with_le(key: str, le: str) -> str:
    """Append the `le` label to a child key."""
    if key == "":
        return "{le=\"" + le + "\"}"
    return key[0:len(key) - 1] + ",le=\"" + le + "\"}"


@dataclass
class Histogram:
    name: str
    documentation: str
    labelnames: list[str] = []
    buckets: list[float] = []
    _key: str = ""

    def __post_init__(self: Mut[Histogram]) -> None:
        if len(self.buckets) == 0:
            self.buckets = [0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0,
                            2.5, 5.0, 7.5, 10.0]
        i: int = 1
        while i < len(self.buckets):
            if self.buckets[i] <= self.buckets[i - 1]:
                raise ValueError("Buckets not in sorted order")
            i += 1
        _register(self.name, "histogram", self.documentation, self.labelnames)
        if mx_meta_get("buckets:" + self.name) == "":
            texts: list[str] = []
            for b in self.buckets:
                texts.append(_fmt(b))
            mx_meta_set("buckets:" + self.name, ",".join(texts))
        if len(self.labelnames) == 0:
            added: bool = mx_meta_add("children:" + self.name, "")

    def labels(self: Ref[Histogram], v1: str = "", v2: str = "", v3: str = "",
               v4: str = "") -> Histogram:
        key: str = _child_key(self.name, self.labelnames, v1, v2, v3, v4)
        bs: list[float] = []
        for b in self.buckets:
            bs.append(b)
        return Histogram(self.name, self.documentation, _copy_names(self.labelnames), move(bs), key)

    def observe(self: Ref[Histogram], amount: float) -> None:
        _check_parent(self.labelnames, self._key, "histogram")
        for b in self.buckets:
            if amount <= b:
                mx_add(self.name + "_bucket" + _with_le(self._key, _fmt(b)), 1.0)
        mx_add(self.name + "_bucket" + _with_le(self._key, "+Inf"), 1.0)
        mx_add(self.name + "_count" + self._key, 1.0)
        mx_add(self.name + "_sum" + self._key, amount)


@dataclass
class Summary:
    name: str
    documentation: str
    labelnames: list[str] = []
    _key: str = ""

    def __post_init__(self: Mut[Summary]) -> None:
        _register(self.name, "summary", self.documentation, self.labelnames)
        if len(self.labelnames) == 0:
            added: bool = mx_meta_add("children:" + self.name, "")

    def labels(self: Ref[Summary], v1: str = "", v2: str = "", v3: str = "", v4: str = "") -> Summary:
        key: str = _child_key(self.name, self.labelnames, v1, v2, v3, v4)
        return Summary(self.name, self.documentation, _copy_names(self.labelnames), key)

    def observe(self: Ref[Summary], amount: float) -> None:
        _check_parent(self.labelnames, self._key, "summary")
        mx_add(self.name + "_count" + self._key, 1.0)
        mx_add(self.name + "_sum" + self._key, amount)


def generate_latest() -> bytes:
    """Every registered metric in the Prometheus text exposition format."""
    out: list[str] = []
    for fam in _split(mx_meta_get("families")):
        kind: str = mx_meta_get("type:" + fam)
        shown: str = fam + "_total" if kind == "counter" else fam
        out.append("# HELP " + shown + " " + _escape_help(mx_meta_get("help:" + fam)))
        out.append("# TYPE " + shown + " " + kind)
        bounds: list[float] = _bucket_bounds(fam)
        for key in _split(mx_meta_get("children:" + fam)):
            if kind == "counter":
                out.append(fam + "_total" + key + " " + _fmt(mx_get(fam + "_total" + key)))
            elif kind == "gauge":
                out.append(fam + key + " " + _fmt(mx_get(fam + key)))
            else:
                if kind == "histogram":
                    for b in bounds:
                        lk: str = _with_le(key, _fmt(b))
                        out.append(fam + "_bucket" + lk + " " + _fmt(mx_get(fam + "_bucket" + lk)))
                    ik: str = _with_le(key, "+Inf")
                    out.append(fam + "_bucket" + ik + " " + _fmt(mx_get(fam + "_bucket" + ik)))
                out.append(fam + "_count" + key + " " + _fmt(mx_get(fam + "_count" + key)))
                out.append(fam + "_sum" + key + " " + _fmt(mx_get(fam + "_sum" + key)))
    if len(out) == 0:
        return b""
    return ("\n".join(out) + "\n").encode("utf-8")
