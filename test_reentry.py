"""Run: python test_reentry.py  (no network, no key). SPEC_REENTREE (20/11/2026): re-entry rules, TEST only.
CYBERLEEK was bought 3 times in 1 h 30 (all losses); FLOAT re-bought and stopped. Rules are OFF by default."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

import pilot
from notify import Notifier
from pilot import FomoPilot, load_pending_followups
from risk import RiskManager, Rules
from scanner import VolumeTracker

pilot.logger.disabled = True

GOOD = dict(price=1.0, volume_24h=300_000, market_cap=5_000_000, age_hours=2, change_30m_pct=25,
            change_1h_pct=60, top5_holders_pct=30, liquidity_usd=600_000, btc_change_1h_pct=-1)
T0 = 1_800_000_000.0


def rm(state_path=None, **opts):
    clock = {"t": T0, "d": "2026-11-20"}
    rules = Rules()
    for k, v in opts.items():
        setattr(rules, k, v)
    m = RiskManager(rules, 1000, state_path=state_path, trade_log=None,
                    today_fn=lambda: clock["d"], now_fn=lambda: clock["t"])
    m.clock = clock
    return m


def stop_out(m, token="CYB", entry=1.0, exit_price=0.87):
    m.open_position(token, entry, 10, 12)
    m.apply_exit(token, 1.0, exit_price, f"stop-loss ({(exit_price / entry - 1) * 100:.1f}%)")


def rules_of(m):
    return [x["rule"] for x in m.last_reentry_refusals]


# ------------------------------------------------------------------------------------------------ rule 1 + 2
def test_cooldown_then_reclaim():
    m = rm(reentry_cooldown_min=20, reentry_reclaim=True)
    stop_out(m)
    m.clock["t"] += 5 * 60
    fails = m.check_entry("CYB", dict(GOOD, price=1.05))
    assert fails and rules_of(m) == ["cooldown"] and "15 min restantes" in fails[0]
    m.clock["t"] += 16 * 60                                       # +21 min: cooldown over
    assert m.check_entry("CYB", dict(GOOD, price=1.05)) == []     # price >= previous entry: allowed
    assert m.check_entry("CYB", dict(GOOD, price=1.00)) == []     # equal is enough
    fails = m.check_entry("CYB", dict(GOOD, price=0.95))          # below previous entry: no reclaim
    assert rules_of(m) == ["reclaim"] and "pas de reprise" in fails[0]
    assert m.check_entry("OTHER", dict(GOOD, price=0.5)) == []    # rules are per token


def test_winning_exit_starts_no_cooldown():
    m = rm(reentry_cooldown_min=20, reentry_reclaim=True)
    m.open_position("FLOAT", 1.0, 10, 12)
    m.apply_exit("FLOAT", 0.4, 1.40, "TP1 (+40%)")
    m.apply_exit("FLOAT", 0.6, 1.30, "trailing stop (-12% from high)")
    m.clock["t"] += 60
    assert m.check_entry("FLOAT", dict(GOOD, price=0.9)) == []    # winner: no cooldown, no reclaim condition


def test_flat_or_volume_exit_counts_as_a_loss():
    m = rm(reentry_cooldown_min=20)
    m.open_position("A", 1.0, 10, 12)
    m.apply_exit("A", 1.0, 1.0, "trailing stop (-12% from high)")  # pnl = 0 -> loss/flat
    assert rules_of(m) == [] and m.check_entry("A", GOOD) and rules_of(m) == ["cooldown"]
    m.open_position("B", 1.0, 10, 12)
    m.apply_exit("B", 1.0, 1.02, "volume drop 70% in 1h")         # volume exit, even at +2 %
    assert m.check_entry("B", GOOD) and rules_of(m) == ["cooldown"]


def test_reclaim_volume_condition():
    m = rm(reentry_reclaim=True)
    stop_out(m)
    assert m.check_entry("CYB", dict(GOOD, price=1.1, volume_drop_1h_pct=35)) and rules_of(m) == ["reclaim"]
    assert m.check_entry("CYB", dict(GOOD, price=1.1, volume_drop_1h_pct=20)) == []
    # volume unknown: historical behaviour (not blocked), as SPEC_REENTREE rule 4 asks
    assert m.check_entry("CYB", dict(GOOD, price=1.1)) == []


# ------------------------------------------------------------------------------------------------ rule 3
def test_max_two_stops_per_token_per_day():
    m = rm(max_stops_per_token_day=2)
    stop_out(m)
    assert m.check_entry("CYB", GOOD) == []                       # 1 stop: still allowed
    stop_out(m)
    fails = m.check_entry("CYB", GOOD)
    assert rules_of(m) == ["max_stops"] and "2 stops aujourd'hui" in fails[0]
    assert m.check_entry("OTHER", GOOD) == []
    m.clock["d"] = "2026-11-21"                                   # next (Paris) day: reset
    assert m.check_entry("CYB", GOOD) == []


# ------------------------------------------------------------------------------------------------ rule 4
def test_no_entry_on_falling_volume():
    m = rm(no_entry_volume_drop_pct=60)
    fails = m.check_entry("CYB", dict(GOOD, volume_drop_1h_pct=65))
    assert rules_of(m) == ["volume_drop"] and "volume en chute (65 %" in fails[0]
    assert m.check_entry("CYB", dict(GOOD, volume_drop_1h_pct=60)) == []     # same strict ">" as the exit rule
    assert m.check_entry("CYB", dict(GOOD, volume_drop_1h_pct=None)) == []   # unknown: historical behaviour
    assert m.check_entry("CYB", GOOD) == []


def test_entry_volume_drop_does_not_touch_the_exit_tracker():
    fp = object.__new__(FomoPilot)
    fp.voltrack = VolumeTracker()
    fp.voltrack.update("CYB", 100_000, now=0)
    fp.voltrack.update("CYB", 100_000, now=10)
    fp.risk = rm(no_entry_volume_drop_pct=60)
    metrics = {"volume_h1": 30_000}
    real_time = pilot.time.time
    import scanner
    scanner_time = scanner.time.time
    scanner.time.time = lambda: 3700
    try:
        fp._entry_volume_drop("CYB", metrics)
    finally:
        scanner.time.time = scanner_time
    assert metrics["volume_drop_1h_pct"] == 70.0 and len(fp.voltrack.hist["CYB"]) == 2   # peek: no new sample
    fp.risk = rm()                                                                     # options off
    metrics = {"volume_h1": 30_000}
    fp._entry_volume_drop("CYB", metrics)
    assert "volume_drop_1h_pct" not in metrics
    assert pilot.time.time is real_time


# ------------------------------------------------------------------------------------------------ off = identical
def test_all_options_off_is_the_historical_behaviour():
    tmp = tempfile.mkdtemp(prefix="fomo-test-")
    try:
        m = rm(state_path=os.path.join(tmp, "state.json"))
        stop_out(m)
        stop_out(m)
        stop_out(m)                                               # CYBERLEEK x3: historically all allowed
        assert m.check_entry("CYB", dict(GOOD, price=0.5, volume_drop_1h_pct=99)) == []
        out = m.process({"intent": "enter", "token": "CYB", "metrics": dict(GOOD, change_1h_pct=1)})
        assert "reentry_refused" not in out
        assert m.token_hist == {}
        saved = json.load(open(os.path.join(tmp, "state.json"), encoding="utf-8"))
        assert set(saved) == {"capital", "day", "day_start_capital", "daily_pnl", "trades_today", "halted",
                              "positions"}                        # exact historical format, no token_hist
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_state_backward_compatible_and_history_persisted():
    tmp = tempfile.mkdtemp(prefix="fomo-test-")
    try:
        path = os.path.join(tmp, "state_test2.json")
        old = {"capital": 999.5, "day": "2026-11-20", "day_start_capital": 1000.0, "daily_pnl": -0.5,
               "trades_today": 1, "halted": False, "positions": {}}
        json.dump(old, open(path, "w", encoding="utf-8"))
        m = rm(state_path=path, reentry_cooldown_min=20)
        assert m.capital == 999.5 and m.token_hist == {}          # old file without token_hist loads as before
        stop_out(m)
        saved = json.load(open(path, encoding="utf-8"))
        assert saved["token_hist"]["CYB"]["last_exit_loss"] is True
        m2 = rm(state_path=path, reentry_cooldown_min=20)        # restart: the cooldown survives
        m2.clock["t"] += 60
        assert m2.check_entry("CYB", GOOD) and rules_of(m2) == ["cooldown"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_refusal_measured_only_when_reentry_is_the_only_reason():
    m = rm(reentry_cooldown_min=20)
    stop_out(m)
    out = m.process({"intent": "enter", "token": "CYB", "metrics": dict(GOOD, change_1h_pct=5), "ref": "solana:X"})
    assert out["entry"] is None and "reentry_refused" not in out  # weak momentum: refused anyway, not measured
    out = m.process({"intent": "enter", "token": "CYB", "metrics": GOOD, "ref": "solana:X"})
    rf = out["reentry_refused"]
    assert len(rf) == 1 and rf[0]["rule"] == "cooldown" and rf[0]["price"] == 1.0 and rf[0]["ref"] == "solana:X"
    assert rf[0]["token"] == "CYB"
    assert m.check_entry("CYB", GOOD, skip={"holders", "flags", "reentry"}) == []   # scan pre-filter ignores them


# ------------------------------------------------------------------------------------------------ +30 / +60 min
def pair(price):
    return {"chainId": "solana", "pairAddress": "P1", "priceUsd": str(price), "baseToken": {"address": "MINT"},
            "liquidity": {"usd": 50_000}, "volume": {"h1": 1, "h24": 1}, "priceChange": {"h1": 1}}


class FakeDex:
    def __init__(self, prices):
        self.prices, self.calls = list(prices), 0

    async def token_pairs(self, address, chain=None):
        self.calls += 1
        p = self.prices.pop(0) if self.prices else None
        return [pair(p)] if p else []


def refusal_pilot(prices):
    tmp = tempfile.mkdtemp(prefix="fomo-test-")
    fp = object.__new__(FomoPilot)
    fp.refusal_log = os.path.join(tmp, "refusals_test2.jsonl")
    fp.refusal_followups, fp.dex, fp.tmp = [], FakeDex(prices), tmp
    return fp


def log_rows(fp):
    return [json.loads(l) for l in open(fp.refusal_log, encoding="utf-8")]


def test_refusal_logged_then_price_at_30_and_60_min():
    fp = refusal_pilot([1.30, 0.80])
    real = pilot.time.time
    pilot.time.time = lambda: T0
    try:
        fp._record_refusal({"token": "CYB", "rule": "cooldown", "reason": "réentrée : cooldown", "price": 1.0,
                            "ref": "solana:MINT"})
    finally:
        pilot.time.time = real
    rows = log_rows(fp)
    assert rows[0]["type"] == "refusal" and rows[0]["rule"] == "cooldown" and rows[0]["price"] == 1.0
    asyncio.run(fp.refusal_followup_step(now=T0 + 10 * 60))      # too early: nothing, no call
    assert fp.dex.calls == 0 and len(log_rows(fp)) == 1
    asyncio.run(fp.refusal_followup_step(now=T0 + 31 * 60))
    asyncio.run(fp.refusal_followup_step(now=T0 + 61 * 60))
    f30, f60 = log_rows(fp)[1:]
    assert f30["after_min"] == 30 and f30["price_30m"] == 1.30 and f30["change_30m_pct"] == 30.0
    assert f60["after_min"] == 60 and f60["price_60m"] == 0.80 and f60["change_60m_pct"] == -20.0
    assert f30["id"] == f60["id"] == rows[0]["id"] and fp.refusal_followups == []
    shutil.rmtree(fp.tmp, ignore_errors=True)


def test_followup_never_writes_a_wrong_time_price():
    fp = refusal_pilot([1.5])
    fp.refusal_followups = [{"id": "x", "token": "CYB", "ref": "solana:MINT", "price": 1.0, "t0": T0, "todo": [30, 60]}]
    asyncio.run(fp.refusal_followup_step(now=T0 + 50 * 60))      # +30 is 20 min late (> 10 min grace)
    rows = log_rows(fp)
    assert rows[0]["after_min"] == 30 and rows[0]["missed"] is True and rows[0]["price_30m"] is None
    assert fp.dex.calls == 0                                       # no fetch for a missed reading
    fp2 = refusal_pilot([])                                        # DexScreener empty -> retry later, nothing written
    fp2.refusal_followups = [{"id": "y", "token": "CYB", "ref": "solana:MINT", "price": 1.0, "t0": T0, "todo": [30]}]
    asyncio.run(fp2.refusal_followup_step(now=T0 + 31 * 60))
    assert not os.path.exists(fp2.refusal_log) and fp2.refusal_followups[0]["todo"] == [30]
    shutil.rmtree(fp.tmp, ignore_errors=True)
    shutil.rmtree(fp2.tmp, ignore_errors=True)


def test_pending_followups_survive_a_restart():
    tmp = tempfile.mkdtemp(prefix="fomo-test-")
    path = os.path.join(tmp, "refusals_test2.jsonl")
    from datetime import datetime, timezone
    ts = datetime.fromtimestamp(T0, timezone.utc).isoformat()
    rows = [{"type": "refusal", "id": "a", "ts": ts, "token": "A", "rule": "cooldown", "price": 1.0, "ref": "solana:M"},
            {"type": "followup", "id": "a", "after_min": 30, "price_30m": 1.1},
            {"type": "refusal", "id": "b", "ts": ts, "token": "B", "rule": "reclaim", "price": 2.0, "ref": "solana:N"},
            {"type": "refusal", "id": "c", "ts": ts, "token": "C", "rule": "cooldown", "price": None, "ref": "solana:O"}]
    open(path, "w", encoding="utf-8").write("\n".join(json.dumps(r) for r in rows) + "\n{broken\n")
    pend = {p["id"]: p["todo"] for p in load_pending_followups(path, now=T0 + 40 * 60)}
    assert pend == {"a": [60], "b": [30, 60]}                      # c has no price: nothing to follow
    assert load_pending_followups(path, now=T0 + 3 * 3600) == []   # too old
    assert load_pending_followups(os.path.join(tmp, "absent.jsonl")) == []
    shutil.rmtree(tmp, ignore_errors=True)


def test_handle_plan_records_refusals():
    fp = refusal_pilot([])
    fp.live, fp.pending, fp.notifier = False, None, Notifier("")
    fp.risk = rm()
    plan = {"log": ["ENTRY REFUSED CYB: réentrée : cooldown"], "exits": [], "entry": None,
            "reentry_refused": [{"rule": "cooldown", "reason": "réentrée : cooldown", "token": "CYB", "price": 1.0,
                                 "ref": "solana:MINT"}]}
    asyncio.run(fp.handle_plan(plan))
    assert log_rows(fp)[0]["rule"] == "cooldown" and len(fp.refusal_followups) == 1
    shutil.rmtree(fp.tmp, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ CLI + workflows
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "NTFY_TOPIC": ""}
OPTS = ("--reentry-cooldown-min", "--reentry-reclaim", "--max-stops-per-token-day", "--no-entry-volume-drop-pct",
        "--refusal-log")


def test_cli_refuses_reentry_options_on_the_real_books():
    for extra in (["--reentry-cooldown-min", "20"], ["--reentry-reclaim", "--state-file", "state_test2.json"],
                  ["--max-stops-per-token-day", "2", "--trade-log", "trades_test2.jsonl"]):
        p = subprocess.run([sys.executable, "pilot.py", "--auto", "--cloud", *extra], capture_output=True,
                           timeout=60, env=ENV)
        assert p.returncode == 1 and "séparés" in p.stdout.decode("utf-8", "replace"), extra
    p = subprocess.run([sys.executable, "pilot.py", "--auto", "--cloud", "--no-entry-volume-drop-pct", "-5",
                        "--state-file", "s2.json", "--trade-log", "t2.jsonl"], capture_output=True, timeout=60, env=ENV)
    assert p.returncode == 1 and ">= 0" in p.stdout.decode("utf-8", "replace")


def _wf(name):
    return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github", "workflows", name),
                encoding="utf-8").read()


def test_real_bot_and_slippage_test_never_use_reentry_options():
    for name in ("bot-cloud.yml", "bot-test.yml"):
        txt = _wf(name)
        for o in OPTS + ("refusals_", "data-test2", "state_test2", "trades_test2"):
            assert o not in txt, (name, o)


def test_bot_test2_is_isolated():
    import yaml
    txt = _wf("bot-test2.yml")
    yaml.safe_load(txt)
    pushes = re.findall(r"HEAD:([\w-]+)", txt)
    assert pushes and set(pushes) == {"data-test2"}, pushes
    assert not re.search(r"\bdata-test\b(?!2)|origin/data\b(?!-)|heads origin data\b(?!-)|fetch origin data\b(?!-)", txt)
    assert not re.search(r"(?<![\w-])state\.json|(?<![\w-])trades\.jsonl|state_test\.json|trades_test\.jsonl", txt)
    assert "--gap-buffer-pct" not in txt and "--exit-slippage-pct" not in txt and "--capital 20" in txt
    assert ("--reentry-cooldown-min 20 --reentry-reclaim --max-stops-per-token-day 2 --no-entry-volume-drop-pct 60"
            in txt)
    assert "--state-file state_test2.json --trade-log trades_test2.jsonl --refusal-log refusals_test2.jsonl" in txt
    assert "secrets." not in txt and "ntfy.sh" not in txt and "schedule:" not in txt
    assert 'default: "7"' in txt and "group: bot-test2" in txt and "gh workflow run bot-test2.yml" in txt
    assert "env.LONG_RUN == '1'" in txt and "MIN_RUN_SECONDS=600" in txt and "--live" not in txt


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
