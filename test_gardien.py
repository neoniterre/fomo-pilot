"""Run: python test_gardien.py  (no network, no Chrome)"""
import socket

from gardien import RestartLimiter, port_open, sanitize_args


def test_limiter():
    r = RestartLimiter(max_per_hour=3)
    assert r.allowed(0) and r.wait_s(0) == 30
    r.record(0); r.record(10)
    assert r.allowed(20) and r.wait_s(20) == 60                   # 2 recent restarts -> 60 s
    r.record(20)
    assert not r.allowed(30)                                       # 3 in the hour -> stop
    assert r.allowed(4000)                                         # an hour later: fine again
    r2 = RestartLimiter(max_per_hour=99)
    for i in range(20):
        r2.record(i)
    assert r2.wait_s(30) == 600                                    # capped at 10 min


def test_live_is_forbidden():
    for bad in (["--auto", "--live"], ["--live=1"]):
        try:
            sanitize_args(bad)
        except SystemExit:
            continue
        raise AssertionError("--live must be refused")
    assert sanitize_args(["--auto"]) == ["--auto"]


def test_port_open():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
    port = s.getsockname()[1]
    assert port_open(port) is True
    s.close()
    assert port_open(port, timeout=0.3) is False


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
