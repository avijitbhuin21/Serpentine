"""serp-redis — redis-py-style Redis client (RESP2) for Serpentine.

`Redis(host, port, db=0, password=None, decode_responses=False, socket_timeout=None)`
with redis-py's method names and reply conversions: `ping/set/get/delete/exists/
incr/incrby/decr/expire/ttl/keys/hset/hget/hgetall/hdel/lpush/rpush/lpop/rpop/
lrange/llen/sadd/srem/sismember/scard/publish/flushdb` plus
`execute_command(*args)`. Values come back as bytes (or str with
`decode_responses=True`), `SET`/`PING` return True, `GET` of a missing key returns
None, `HGETALL` returns a dict. Server errors raise `ResponseError` and socket
problems `ConnectionError`, both under `RedisError`.

Caps: one connection per client (no pool), no pipelines/transactions/pub-sub
subscribe/RESP3/TLS; replies are dynamic values (PyVal); `HGETALL` field names are
always str (values follow decode_responses); `execute_command` and
multi-key `delete`/`exists` take a list instead of *args.
"""
from __future__ import annotations
from serpentine import Mut, Owned, PyVal, Ref, dataclass, move, pyval_kind
from _serp_socket import connect as _connect
from _serp_socket import send_all as _send_all
from _serp_socket import recv as _recv
from _serp_socket import close as _close
from _serp_socket import set_timeout as _set_timeout


class RedisError(Exception):
    pass


class ConnectionError(RedisError):
    pass


class ResponseError(RedisError):
    pass


def _encode(args: Ref[list[str]]) -> bytes:
    """A command as a RESP array of bulk strings."""
    out: bytearray = bytearray(b"")
    out.extend(("*" + str(len(args)) + "\r\n").encode("utf-8"))
    for a in args:
        data: bytes = a.encode("utf-8")
        out.extend(("$" + str(len(data)) + "\r\n").encode("utf-8"))
        out.extend(data)
        out.extend(b"\r\n")
    return bytes(out)


@dataclass
class Redis:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    decode_responses: bool = False
    socket_timeout: float | None = None
    _fd: int = -1
    _buf: bytes = b""

    def _ensure(self: Mut[Redis]) -> None:
        if self._fd >= 0:
            return
        ms: int = 0
        if self.socket_timeout is not None:
            ms = int(self.socket_timeout * 1000.0)
        try:
            self._fd = _connect(self.host, self.port, ms)
        except OSError as e:
            raise ConnectionError(f"Error connecting to {self.host}:{self.port}. {e}.")
        if ms > 0:
            _set_timeout(self._fd, ms)
        if self.password is not None:
            auth: list[str] = ["AUTH", self.password]
            r: PyVal = self._roundtrip(auth)
        if self.db != 0:
            sel: list[str] = ["SELECT", str(self.db)]
            r2: PyVal = self._roundtrip(sel)

    def _fill(self: Mut[Redis]) -> None:
        chunk: bytes = b""
        try:
            chunk = _recv(self._fd, 65536)
        except OSError as e:
            self._drop()
            raise ConnectionError(f"Error while reading from {self.host}:{self.port}: {e}")
        if len(chunk) == 0:
            self._drop()
            raise ConnectionError("Connection closed by server.")
        self._buf = self._buf + chunk

    def _line(self: Mut[Redis]) -> bytes:
        at: int = self._buf.find(b"\r\n")
        while at < 0:
            self._fill()
            at = self._buf.find(b"\r\n")
        line: bytes = self._buf[0:at]
        self._buf = self._buf[at + 2:len(self._buf)]
        return line

    def _exact(self: Mut[Redis], n: int) -> bytes:
        while len(self._buf) < n + 2:
            self._fill()
        data: bytes = self._buf[0:n]
        self._buf = self._buf[n + 2:len(self._buf)]
        return data

    def _text(self: Ref[Redis], data: bytes) -> PyVal:
        if self.decode_responses:
            return data.decode("utf-8")
        return data

    def _read(self: Mut[Redis]) -> PyVal:
        line: bytes = self._line()
        if len(line) == 0:
            raise ResponseError("Protocol error: empty reply line")
        kind: str = line[0:1].decode("utf-8")
        rest: str = line[1:len(line)].decode("utf-8")
        if kind == "+":
            return self._text(rest.encode("utf-8"))
        if kind == "-":
            raise ResponseError(rest)
        if kind == ":":
            return int(rest)
        if kind == "$":
            n: int = int(rest)
            if n < 0:
                return None
            data: bytes = self._exact(n)
            return self._text(data)
        if kind == "*":
            m: int = int(rest)
            if m < 0:
                return None
            items: list[PyVal] = []
            i: int = 0
            while i < m:
                items.append(self._read())
                i += 1
            return move(items)
        raise ResponseError(f"Protocol error, got {kind!r} as reply type byte")

    def _drop(self: Mut[Redis]) -> None:
        if self._fd >= 0:
            try:
                _close(self._fd)
            except OSError as e:
                pass
        self._fd = -1
        self._buf = b""

    def _roundtrip(self: Mut[Redis], args: Ref[list[str]]) -> PyVal:
        try:
            n: int = _send_all(self._fd, _encode(args), 0)
        except OSError as e:
            self._drop()
            raise ConnectionError(f"Error while writing to {self.host}:{self.port}: {e}")
        return self._read()

    def execute_command(self: Mut[Redis], args: Owned[list[str]]) -> PyVal:
        """Send one raw command (a list of its words) and return the decoded reply."""
        self._ensure()
        return self._roundtrip(args)

    def _ok(self: Mut[Redis], args: Owned[list[str]]) -> bool:
        r: PyVal = self.execute_command(move(args))
        return r is not None

    def _int(self: Mut[Redis], args: Owned[list[str]]) -> int:
        r: PyVal = self.execute_command(move(args))
        return int(r)

    def ping(self: Mut[Redis]) -> bool:
        return self._ok(["PING"])

    def set(self: Mut[Redis], name: str, value: str, ex: int | None = None,
            px: int | None = None, nx: bool = False, xx: bool = False) -> bool | None:
        args: list[str] = ["SET", name, value]
        if ex is not None:
            args.append("EX")
            args.append(str(ex))
        if px is not None:
            args.append("PX")
            args.append(str(px))
        if nx:
            args.append("NX")
        if xx:
            args.append("XX")
        r: PyVal = self.execute_command(move(args))
        if r is None:
            return None
        return True

    def get(self: Mut[Redis], name: str) -> PyVal:
        return self.execute_command(["GET", name])

    def delete(self: Mut[Redis], names: Owned[list[str]]) -> int:
        args: list[str] = ["DEL"]
        for n in names:
            args.append(n)
        return self._int(move(args))

    def exists(self: Mut[Redis], names: Owned[list[str]]) -> int:
        args: list[str] = ["EXISTS"]
        for n in names:
            args.append(n)
        return self._int(move(args))

    def incr(self: Mut[Redis], name: str, amount: int = 1) -> int:
        if amount == 1:
            return self._int(["INCR", name])
        return self._int(["INCRBY", name, str(amount)])

    def incrby(self: Mut[Redis], name: str, amount: int = 1) -> int:
        return self._int(["INCRBY", name, str(amount)])

    def decr(self: Mut[Redis], name: str, amount: int = 1) -> int:
        if amount == 1:
            return self._int(["DECR", name])
        return self._int(["DECRBY", name, str(amount)])

    def expire(self: Mut[Redis], name: str, time: int) -> bool:
        return self._int(["EXPIRE", name, str(time)]) == 1

    def ttl(self: Mut[Redis], name: str) -> int:
        return self._int(["TTL", name])

    def keys(self: Mut[Redis], pattern: str = "*") -> PyVal:
        return self.execute_command(["KEYS", pattern])

    def hset(self: Mut[Redis], name: str, key: str, value: str) -> int:
        return self._int(["HSET", name, key, value])

    def hget(self: Mut[Redis], name: str, key: str) -> PyVal:
        return self.execute_command(["HGET", name, key])

    def hdel(self: Mut[Redis], name: str, key: str) -> int:
        return self._int(["HDEL", name, key])

    def hgetall(self: Mut[Redis], name: str) -> PyVal:
        flat: PyVal = self.execute_command(["HGETALL", name])
        out: dict[str, PyVal] = {}
        i: int = 0
        while i + 1 < len(flat):
            k: PyVal = flat[i]
            key: str = ""
            if pyval_kind(k) == "bytes":
                key = bytes(k).decode("utf-8")
            else:
                key = str(k)
            out[key] = flat[i + 1]
            i += 2
        res: PyVal = move(out)
        return res

    def lpush(self: Mut[Redis], name: str, value: str) -> int:
        return self._int(["LPUSH", name, value])

    def rpush(self: Mut[Redis], name: str, value: str) -> int:
        return self._int(["RPUSH", name, value])

    def lpop(self: Mut[Redis], name: str) -> PyVal:
        return self.execute_command(["LPOP", name])

    def rpop(self: Mut[Redis], name: str) -> PyVal:
        return self.execute_command(["RPOP", name])

    def lrange(self: Mut[Redis], name: str, start: int, end: int) -> PyVal:
        return self.execute_command(["LRANGE", name, str(start), str(end)])

    def llen(self: Mut[Redis], name: str) -> int:
        return self._int(["LLEN", name])

    def sadd(self: Mut[Redis], name: str, value: str) -> int:
        return self._int(["SADD", name, value])

    def srem(self: Mut[Redis], name: str, value: str) -> int:
        return self._int(["SREM", name, value])

    def sismember(self: Mut[Redis], name: str, value: str) -> bool:
        return self._int(["SISMEMBER", name, value]) == 1

    def scard(self: Mut[Redis], name: str) -> int:
        return self._int(["SCARD", name])

    def publish(self: Mut[Redis], channel: str, message: str) -> int:
        return self._int(["PUBLISH", channel, message])

    def flushdb(self: Mut[Redis]) -> bool:
        return self._ok(["FLUSHDB"])

    def close(self: Mut[Redis]) -> None:
        self._drop()
