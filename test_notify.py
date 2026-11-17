"""Run: python test_notify.py  (no network)"""
import asyncio

from notify import Notifier, msg_entry, msg_exit, msg_report


def test_disabled_without_topic():
    import os
    os.environ.pop("NTFY_TOPIC", None)
    n = Notifier()
    assert not n.enabled and asyncio.run(n.send("t", "m")) is False


def test_never_raises_and_counts_errors():
    import sys, types
    fake = types.ModuleType("httpx")
    class Bad:
        def __init__(self, *a, **k):
            raise RuntimeError("offline")
    fake.AsyncClient = Bad
    old = sys.modules.get("httpx")
    sys.modules["httpx"] = fake
    try:
        n = Notifier("topic-test")
        assert asyncio.run(n.send("t", "m")) is False and n.errors == 1
    finally:
        if old is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = old


def test_dedupe():
    n = Notifier("topic-test", dedupe_s=60)
    assert n._skip("a", 0) is False
    assert n._skip("a", 30) is True        # same message within 60 s
    assert n._skip("a", 100) is False      # later it goes out again
    assert n._skip("b", 30) is False


def test_messages():
    t, m = msg_entry({"token": "GTA6", "usd": 3.5, "stop_pct": 12})
    assert "GTA6" in t and "3.50" in m and "-12%" in m
    t, m = msg_exit({"token": "GTA6", "reason": "TP1", "frac": 0.4}, -1.234)
    assert "-1.23" in t and "40%" in m
    t, m = msg_report(21.5, 20.0, 2, ["GTA6"], True)
    assert "+1.50" in m and "GTA6" in m and "Coupe-circuit" in m


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
