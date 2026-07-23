from serp_socket import (AF_INET, SHUT_WR, SOCK_DGRAM, SOCK_STREAM,
                         create_connection, gaierror, socket, timeout)


def main() -> None:
    lst: socket = socket(AF_INET, SOCK_STREAM)
    lst.bind(("127.0.0.1", 0))
    lst.listen(16)
    sn: tuple[str, int] = lst.getsockname()
    port: int = sn[1]
    print(port > 0)

    cli: socket = create_connection(("127.0.0.1", port), 2.0)
    srv: socket = lst.accept()
    print(cli.send(b"hello from client"))
    print(srv.recv(1024))
    print(srv.send(b"hi from server"))
    print(cli.recv(5))
    print(cli.recv(1024))
    cli.shutdown(SHUT_WR)
    print(srv.recv(1024))
    cli.close()
    srv.close()

    cli2: socket = socket()
    cli2.connect(("127.0.0.1", port))
    srv2: socket = lst.accept()
    cli2.settimeout(0.1)
    gt: float | None = cli2.gettimeout()
    if gt is not None:
        print(gt)
    try:
        junk: bytes = cli2.recv(10)
        print(len(junk))
    except timeout as e:
        print("timeout:", e)
    cli2.close()
    srv2.close()
    lst.close()

    tmp: socket = socket(AF_INET, SOCK_STREAM)
    tmp.bind(("127.0.0.1", 0))
    deadname: tuple[str, int] = tmp.getsockname()
    deadport: int = deadname[1]
    tmp.close()
    try:
        bad: socket = create_connection(("127.0.0.1", deadport), 1.5)
        print(bad.fileno())
    except OSError as e:
        print("dead port raised:", str(e) == "timed out" or str(e) == "connection refused")

    c3: socket = socket(AF_INET, SOCK_STREAM)
    try:
        c3.connect(("definitely-not-a-real-host.invalid", 80))
        print(c3.fileno())
    except gaierror as e:
        print("resolve:", e)

    u: socket = socket(AF_INET, SOCK_DGRAM)
    u.bind(("127.0.0.1", 0))
    us: tuple[str, int] = u.getsockname()
    uport: int = us[1]
    print(u.sendto(b"datagram!", ("127.0.0.1", uport)))
    r: tuple[bytes, tuple[str, int]] = u.recvfrom(100)
    print(r[0])
    addr: tuple[str, int] = r[1]
    print(addr[0], addr[1] == uport)
    u.settimeout(0.1)
    try:
        r2: tuple[bytes, tuple[str, int]] = u.recvfrom(100)
        print(len(r2[0]))
    except timeout as e:
        print("udp timeout:", e)
    u.close()

    try:
        z: socket = socket(AF_INET, SOCK_STREAM, 0, 999)
        n: int = z.send(b"x")
        print(n)
    except ValueError as e:
        print("handle:", e)

    try:
        w: socket = socket()
        w.connect(("127.0.0.1", 99999))
        print(w.fileno())
    except ValueError as e:
        print("port:", e)

    print("done")


if __name__ == "__main__":
    main()
