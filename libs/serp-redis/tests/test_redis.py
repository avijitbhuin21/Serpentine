"""serp-redis against a scripted RESP server: every command's exact wire bytes are
echoed back by the server thread, and each reply type (simple, error, integer,
bulk, null bulk, arrays with nulls) is decoded the way redis-py does."""
from __future__ import annotations

from _serp_socket import accept, close, listen, local_port, recv, send_all
from serp_redis import ConnectionError, Redis, RedisError, ResponseError
from serpentine import Owned, PyVal, Ref, move, spawn


def parse_command(buf: Ref[bytes]) -> int:
    """Bytes used by one complete RESP command at the front of buf (0 if incomplete)."""
    at: int = buf.find(b"\r\n")
    if at < 0:
        return 0
    n: int = int(buf[1:at].decode("utf-8"))
    pos: int = at + 2
    i: int = 0
    while i < n:
        rel: int = buf[pos:len(buf)].find(b"\r\n")
        if rel < 0:
            return 0
        e: int = pos + rel
        ln: int = int(buf[pos + 1:e].decode("utf-8"))
        pos = e + 2 + ln + 2
        if pos > len(buf):
            return 0
        i += 1
    return pos


def serve_one(fd: int, replies: Owned[list[bytes]]) -> str:
    """Accept one client, answer each command with the next scripted reply, log the commands."""
    c: int = accept(fd)
    log: list[str] = []
    buf: bytes = b""
    for reply in replies:
        used: int = parse_command(buf)
        while used == 0:
            chunk: bytes = recv(c, 65536)
            if len(chunk) == 0:
                break
            buf = buf + chunk
            used = parse_command(buf)
        if used == 0:
            break
        log.append(buf[0:used].decode("utf-8").replace("\r\n", "|"))
        buf = buf[used:len(buf)]
        n: int = send_all(c, reply, 0)
    close(c)
    return "\n".join(log)


def server(fd: int) -> str:
    """Two scripted sessions: bytes replies, then decode_responses=True and a hang-up."""
    first: list[bytes] = [b"+OK\r\n", b"+OK\r\n", b"+PONG\r\n", b"+OK\r\n", b"$-1\r\n",
                          b"$5\r\nhello\r\n", b"$-1\r\n", b":1\r\n", b":6\r\n", b":1\r\n",
                          b"*4\r\n$1\r\na\r\n$1\r\n1\r\n$1\r\nb\r\n$1\r\n2\r\n",
                          b"*3\r\n$1\r\nx\r\n$0\r\n\r\n$-1\r\n", b":2\r\n", b":1\r\n", b":5\r\n",
                          b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n",
                          "$6\r\nhéllo\r\n".encode("utf-8"), b":1\r\n", b"*0\r\n"]
    second: list[bytes] = [b"$3\r\nabc\r\n", b"*2\r\n$1\r\nk\r\n$1\r\nv\r\n", b"*-1\r\n"]
    a: str = serve_one(fd, move(first))
    b: str = serve_one(fd, move(second))
    return a + "\n--\n" + b


def main() -> None:
    fd: int = listen("127.0.0.1", 0)
    port: int = local_port(fd)
    h = spawn(server, fd)

    r: Redis = Redis("127.0.0.1", port, db=2, password="s3cret", socket_timeout=5.0)
    print(r.ping())
    print(r.set("k", "hello", ex=10), r.set("k", "other", nx=True))
    print(r.get("k"), r.get("missing"))
    print(r.incr("c"), r.incr("c", 5))
    print(r.hset("h", "a", "1"), r.hgetall("h"))
    print(r.lrange("l", 0, -1))
    print(r.delete(["a", "b"]), r.expire("k", 5), r.ttl("k"))
    try:
        r.get("wrongtype")
    except ResponseError as e:
        print("ResponseError:", e)
    print(r.execute_command(["ECHO", "héllo"]))
    print(r.sismember("s", "x"), r.keys("nomatch*"))
    r.close()

    d: Redis = Redis("127.0.0.1", port, decode_responses=True)
    print(d.get("k"), d.hgetall("h"), d.lrange("none", 0, 1))
    try:
        d.get("k")
    except ConnectionError as e2:
        print("ConnectionError:", "closed by server" if "reset" in str(e2) or "closed" in str(e2) else "other")
    d.close()

    print(h.join())
    close(fd)

    dead: Redis = Redis("127.0.0.1", port, socket_timeout=1.0)
    try:
        dead.ping()
    except ConnectionError as e3:
        print("refused: ConnectionError")


if __name__ == "__main__":
    main()
