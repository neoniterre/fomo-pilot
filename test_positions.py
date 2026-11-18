"""Run: python test_positions.py  (no network, no key).
SPEC_STOP_SLIPPAGE (18/11/2026, CYBERLEEK stop -12 % filled at -20.1 %): dedicated position loop, trace, exit price."""
import asyncio
import json
import os
import shutil
import tempfile
import types

import pilot
from notify import Notifier
from pilot import FomoPilot
from risk import RiskManager, Rules
from scanner import VolumeTracker

pilot.logger.disabled = True     # never write test lines into the real pilot.log

ADDR = "CybLeekMint1111111111111111111111111111111"


def pair(pool, price, liq):
    return {"chainId": "solana", "pairAddress": pool, "priceUsd": str(price),
            "baseToken": {"address": ADDR, "symbol": "CYB"}, "liquidity": {"usd": liq},
            "volume": {"h1": 5000, "h24": 90000}, "priceChange": {"h1": 1.0}, "marketCap": 3_000_000,
            "pairCreatedAt": 1}


class FakeDex:
    """Each token_pairs call returns the next scripted reading (list of pairs, [] = missed, "429" = rate limited)."""

    def __init__(self, readings):
        self.readings, self.calls, self.rate_limited, self.errors = list(readings), 0, 0, 0

    async def token_pairs(self, address, chain=None):
        self.calls += 1
        r = self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        if r == "429":
            self.rate_limited += 1
            return []
        return r


def make_pilot(readings, entry=1.0, main_pool="P1", watch_interval=5.0):
    tmp = tempfile.mkdtemp(prefix="fomo-test-")
    fp = object.__new__(FomoPilot)
    fp.args = types.SimpleNamespace(state_file=os.path.join(tmp, "state.json"), watch_interval=watch_interval,
                                    auto=True)
    fp.live, fp.pending, fp.running = False, None, True
    fp.risk = RiskManager(Rules(), 1000, state_path=None, trade_log=None)
    fp.dex, fp.voltrack, fp.notifier = FakeDex(readings), VolumeTracker(), Notifier("")
    fp.risk.open_position("CYB", entry, 1.33, 12, ref=f"solana:{ADDR}")
    fp._main_pool = {"CYB": main_pool}                       # as recorded at entry (_entry_on_main_pool)
    exits = []
    real = fp.risk.apply_exit

    def spy(token, frac, price, reason, **kw):
        pnl = real(token, frac, price, reason, **kw)
        exits.append({"token": token, "frac": frac, "price": price, "reason": reason, "pnl": pnl})
        return pnl
    fp.risk.apply_exit = spy
    fp.exits, fp.tmp = exits, tmp
    return fp


def trace(fp):
    path = os.path.join(fp.tmp, pilot.POSITION_TRACE_FILE)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def run_readings(fp, n):
    for _ in range(n):
        asyncio.run(fp.watch_positions())


def done(fp):
    shutil.rmtree(fp.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------- spec §2
def test_fast_drop_exits_at_first_reading_below_stop():
    """0 % -> -10 % -> -25 % in 3 readings: no exit at -10 %, exit at the first reading <= -12 % (here -25 %).
    The fill is the observed price: a gap between two readings IS the slippage (why readings every 5 s)."""
    fp = make_pilot([[pair("P1", 1.00, 100_000)], [pair("P1", 0.90, 100_000)], [pair("P1", 0.75, 100_000)]])
    run_readings(fp, 2)
    assert fp.exits == [] and "CYB" in fp.risk.positions
    run_readings(fp, 1)
    assert len(fp.exits) == 1 and "CYB" not in fp.risk.positions
    ex = fp.exits[0]
    assert ex["price"] == 0.75 and ex["frac"] == 1.0 and ex["reason"] == "stop-loss (-25.0%)"
    assert abs(ex["pnl"] - 1.33 * (0.75 - 1.0)) < 1e-9                       # -0.3325 $ = 2.1 x the planned risk
    t = trace(fp)
    assert [r["change_vs_entry_pct"] for r in t] == [0.0, -10.0, -25.0]
    assert [r["closed"] for r in t] == [False, False, True] and not any(r["missed"] for r in t)
    done(fp)


def test_new_small_pool_moves_the_average_but_not_the_stop():
    """A small pool appears at 0.55 next to the main pool at 1.00: the liquidity-weighted average falls 15 %
    while the main pool does not move. BEFORE the fix the stop used the average -> false stop-loss at -15 %.
    NOW exits use the main pool -> no exit."""
    fp = make_pilot([[pair("P1", 1.00, 100_000)], [pair("P1", 1.00, 100_000), pair("P2", 0.55, 50_000)]])
    run_readings(fp, 2)
    t = trace(fp)
    assert round(t[1]["price_avg"], 6) == 0.85 and t[1]["n_pools"] == 2       # what the OLD code used: -15 %
    assert (t[1]["price_avg"] / 1.0 - 1) * 100 <= -12                          # -> old code: stop-loss, wrongly
    assert t[1]["price"] == 1.00 and t[1]["change_vs_entry_pct"] == 0.0        # new code: main pool price
    assert fp.exits == [] and "CYB" in fp.risk.positions
    done(fp)


def test_disappearing_small_pool_does_not_trigger_anything():
    fp = make_pilot([[pair("P1", 1.00, 100_000), pair("P2", 1.40, 60_000)], [pair("P1", 1.00, 100_000)]])
    run_readings(fp, 2)
    t = trace(fp)
    assert t[0]["price_avg"] > 1.10 and t[1]["price_avg"] == 1.00             # average jumps -13.6 % ...
    assert [r["price"] for r in t] == [1.00, 1.00] and fp.exits == []         # ... the exit price does not
    done(fp)


def test_main_pool_removed_exits_on_the_lower_price():
    """The main pool disappears (typical rug): the new main pool is used AND the lower of (main, average),
    so a real crash is never caught later than before."""
    fp = make_pilot([[pair("P1", 1.00, 100_000)], [pair("P2", 0.80, 20_000), pair("P3", 0.90, 5_000)]])
    run_readings(fp, 2)
    t = trace(fp)
    assert t[1]["main_pool"] == "P2" and t[1]["main_pool_changed"] is True
    assert t[1]["price"] == 0.80 and t[1]["price_avg"] > 0.80                 # min(main 0.80, avg 0.82)
    assert len(fp.exits) == 1 and fp.exits[0]["reason"] == "stop-loss (-20.0%)"
    done(fp)


def test_missed_reading_is_traced_and_keeps_the_position():
    fp = make_pilot([[pair("P1", 1.00, 100_000)], []])
    run_readings(fp, 2)
    t = trace(fp)
    assert t[1]["missed"] is True and t[1]["price"] is None and t[1]["n_pools"] == 0
    assert "CYB" in fp.risk.positions and fp.exits == []
    done(fp)


def test_trace_never_breaks_the_bot():
    fp = make_pilot([[pair("P1", 0.80, 100_000)]])
    fp.args.state_file = os.path.join(fp.tmp, "no", "such", "dir", "state.json")   # unwritable trace path
    run_readings(fp, 1)
    assert len(fp.exits) == 1                                                  # exit still happens
    done(fp)


# ---------------------------------------------------------------------------------------------- spec §4 (priority)
def test_position_loop_keeps_its_pace_during_a_long_scan():
    fp = make_pilot([[pair("P1", 1.00, 100_000)]], watch_interval=0.02)

    async def scenario():
        task = asyncio.create_task(fp.position_watcher())
        await asyncio.sleep(0.4)                       # a slow scan (headless page + 20 DexScreener searches)
        fp.running = False
        await task
    asyncio.run(scenario())
    assert fp.dex.calls >= 8, fp.dex.calls            # ~20 readings expected in 0.4 s at 0.02 s
    done(fp)


def test_position_loop_slows_down_on_429_then_comes_back():
    fp = make_pilot(["429", "429", [pair("P1", 1.00, 100_000)]], watch_interval=5.0)
    slept = []
    real_sleep = pilot.asyncio.sleep

    async def fake_sleep(s):
        slept.append(s)
        if len(slept) >= 4:
            fp.running = False
    pilot.asyncio.sleep = fake_sleep
    try:
        asyncio.run(fp.position_watcher())
    finally:
        pilot.asyncio.sleep = real_sleep
    assert slept == [10.0, 20.0, 5.0, 5.0], slept
    done(fp)


def test_no_reading_without_open_position():
    fp = make_pilot([[pair("P1", 1.00, 100_000)]], watch_interval=5.0)
    fp.risk.positions.clear()
    real_sleep = pilot.asyncio.sleep

    async def fake_sleep(s):
        fp.running = False
    pilot.asyncio.sleep = fake_sleep
    try:
        asyncio.run(fp.position_watcher())
    finally:
        pilot.asyncio.sleep = real_sleep
    assert fp.dex.calls == 0
    done(fp)


def test_cli_watch_interval_minimum_5s():
    import subprocess
    import sys
    p = subprocess.run([sys.executable, "pilot.py", "--help"], capture_output=True, timeout=60)
    assert b"--watch-interval" in p.stdout
    assert pilot.MIN_WATCH_INTERVAL == 5.0 and pilot.POSITION_TRACE_FILE == "position_trace.jsonl"


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
