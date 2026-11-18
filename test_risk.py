"""Run: python test_risk.py   (no network, no API key needed)"""
from risk import RiskManager, Rules, ui_gate

GOOD = dict(price=1.0, volume_24h=300_000, market_cap=5_000_000, age_hours=2,
            change_30m_pct=25, change_1h_pct=60, top5_holders_pct=30,
            liquidity_usd=600_000, btc_change_1h_pct=-1)


def rm(capital=1000.0, day="2026-11-16"):
    box = {"d": day}
    m = RiskManager(Rules(), capital, state_path=None, trade_log=None, today_fn=lambda: box["d"])
    m._box = box
    return m


def test_entry_ok_and_fail_closed():
    m = rm()
    assert m.check_entry("AAA", GOOD) == []
    bad = dict(GOOD); del bad["top5_holders_pct"]
    assert any("missing" in f for f in m.check_entry("AAA", bad))   # unreadable = refused
    bad = dict(GOOD, volume_24h=100_000)
    assert m.check_entry("AAA", bad)
    # option B: momentum = +50% on 1h only; 30m is ignored by default
    assert m.check_entry("AAA", dict(GOOD, change_30m_pct=25, change_1h_pct=10))
    assert m.check_entry("AAA", dict(GOOD, change_30m_pct=5, change_1h_pct=60)) == []
    nom = dict(GOOD); del nom["change_30m_pct"]
    assert m.check_entry("AAA", nom) == []                           # 30m not required in option B
    # option A kept available: +20% 30m OR +50% 1h
    m30 = RiskManager(Rules(use_30m=True), 1000, state_path=None, trade_log=None)
    assert m30.check_entry("AAA", dict(GOOD, change_30m_pct=25, change_1h_pct=10)) == []
    assert any("missing" in f for f in m30.check_entry("AAA", nom))
    assert m.check_entry("AAA", dict(GOOD, liquidity_usd=100_000))  # liq/mcap 2% < 8%
    assert m.check_entry("AAA", dict(GOOD, market_cap=90_000_000))
    assert m.check_entry("AAA", dict(GOOD, age_hours=0.5))
    assert m.check_entry("AAA", dict(GOOD, btc_change_1h_pct=-5))   # BTC block


def test_gap_buffer_and_exit_slippage_off_by_default():
    r = Rules()
    assert r.gap_buffer_pct == 0.0 and r.exit_slippage_pct == 0.0           # historical behaviour unchanged
    assert rm(20).size_position(GOOD)[0] == 1.33
    m = rm(1000)
    m.open_position("A", 1.0, 50, 12)
    assert abs(m.apply_exit("A", 1.0, 0.8, "stop-loss (-20.0%)") - (-10.0)) < 1e-9   # filled at observed price


def test_gap_buffer_keeps_a_cyberleek_gap_within_the_planned_risk():
    """CYBERLEEK 18/11: stop -12 % filled at -20.1 %. Risk 0.8 % of 1000 $ = 8 $."""
    plain = rm(1000)
    size, _, _ = plain.size_position(GOOD)                                   # 8 / 0.12 = 66.67
    loss_plain = size * 0.201
    buf = rm(1000)
    buf.r.gap_buffer_pct = 8.0
    size_b, stop, notes = buf.size_position(GOOD)
    assert stop == 12 and size_b == 40.0 and "gap buffer 8.0%" in notes[0]   # 8 / 0.20
    loss_buf = size_b * 0.201
    assert loss_plain > 13 and abs(loss_buf - 8.04) < 0.01                   # 1.7 x the risk -> ~1.0 x
    # 20 $ account: 0.16 / 0.20 = 0.80 $ < 1 $ minimum -> NO trade at all (why a test needs more capital)
    small = rm(20)
    small.r.gap_buffer_pct = 8.0
    size_s, _, notes_s = small.size_position(GOOD)
    assert size_s == 0.0 and any("below minimum" in n for n in notes_s)
    ok = rm(30)
    ok.r.gap_buffer_pct = 8.0
    assert ok.size_position(GOOD)[0] == 1.2                                  # 0.24 / 0.20


def test_exit_slippage_is_pessimistic_and_logged():
    import json, os, tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="fomo-test-"), "trades_test.jsonl")
    m = RiskManager(Rules(), 1000, state_path=None, trade_log=path)
    m.r.exit_slippage_pct = 1.0
    m.open_position("A", 1.0, 40, 12)
    pnl = m.apply_exit("A", 1.0, 0.80, "stop-loss (-20.0%)")
    assert abs(pnl - 40 * (0.792 - 1.0)) < 1e-9                              # filled at 0.80 x 0.99
    sell = [json.loads(l) for l in open(path, encoding="utf-8")][-1]
    assert sell["theoretical_price"] == 0.80 and abs(sell["fill_price"] - 0.792) < 1e-12
    assert sell["slippage_pct"] == -1.0
    # live fills are never touched by the paper option
    m.open_position("B", 1.0, 40, 12, mode="live")
    pnl_live = m.apply_exit("B", 1.0, 0.80, "stop-loss (-20.0%)", mode="live")
    assert abs(pnl_live - 40 * (0.80 - 1.0)) < 1e-9


def test_test_options_refuse_the_real_books():
    import subprocess, sys
    for extra in (["--gap-buffer-pct", "8"],
                  ["--exit-slippage-pct", "1", "--state-file", "state_test.json"],          # trades.jsonl still real
                  ["--gap-buffer-pct", "8", "--trade-log", "trades_test.jsonl"]):           # state.json still real
        p = subprocess.run([sys.executable, "pilot.py", "--auto", "--cloud", *extra], capture_output=True,
                           timeout=60, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "NTFY_TOPIC": ""})
        assert p.returncode == 1 and "séparés" in p.stdout.decode("utf-8", "replace"), extra
    p = subprocess.run([sys.executable, "pilot.py", "--auto", "--cloud", "--gap-buffer-pct", "-3",
                        "--state-file", "s_t.json", "--trade-log", "t_t.jsonl"], capture_output=True, timeout=60,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "NTFY_TOPIC": ""})
    assert p.returncode == 1 and ">= 0" in p.stdout.decode("utf-8", "replace")


def test_sizing():
    m = rm(1000)
    size, stop, _ = m.size_position(GOOD)
    assert stop == 12 and abs(size - 66.67) < 0.01                  # 8 / 0.12
    # exposure cap 25% = 250 -> 3 positions of 66.67 = 200, 4th capped at 50
    for t in "ABC":
        m.open_position(t, 1.0, 66.67, 12)
    size, _, notes = m.size_position(GOOD)
    assert abs(size - 50.0) < 0.05 and any("exposure" in n for n in notes)
    # pool cap: 1.5% of 2000$ liquidity = 30$
    m2 = rm(1000)
    size, _, _ = m2.size_position(dict(GOOD, liquidity_usd=2000))
    assert size == 30.0
    # stop clamp
    assert rm().size_position(GOOD, stop_pct=20)[1] == 15
    # small account (20$): 0.16 / 0.12 = 1.33$
    assert rm(20).size_position(GOOD)[0] == 1.33


def test_max_positions_and_trades():
    m = rm(1000)
    for t in "ABCDE":
        m.open_position(t, 1.0, 10, 12)
    assert any("max positions" in f for f in m.check_entry("Z", GOOD))
    m = rm(1000)
    m.trades_today = 15
    assert any("trades/day" in f for f in m.check_entry("Z", GOOD))


def test_exits():
    m = rm()
    m.open_position("A", 100.0, 50, 12)
    assert m.evaluate_exits("A", 120) == []
    ex = m.evaluate_exits("A", 140)
    assert len(ex) == 1 and ex[0][0] == 0.4 and ex[0][1].startswith("TP1")
    m.apply_exit("A", 0.4, 140, ex[0][1])
    # jump straight to TP2
    ex = m.evaluate_exits("A", 180)
    assert ex[0][1].startswith("TP2") and abs(ex[0][0] - 0.3) < 1e-9
    m.apply_exit("A", 0.3, 180, ex[0][1])
    # trailing: high 180 -> exit under 158.4
    assert m.evaluate_exits("A", 165) == []
    ex = m.evaluate_exits("A", 158)
    assert ex and ex[0][1].startswith("trailing") and abs(ex[0][0] - 0.3) < 1e-9
    m.apply_exit("A", ex[0][0], 158, ex[0][1])
    assert "A" not in m.positions
    # stop-loss and volume drop
    m.open_position("B", 100.0, 50, 12)
    assert m.evaluate_exits("B", 87)[0][1].startswith("stop-loss")
    assert m.evaluate_exits("B", 100, volume_drop_1h_pct=65)[0][1].startswith("volume")
    assert m.evaluate_exits("B", 100, volume_drop_1h_pct=50) == []


def test_no_trailing_before_tp1():
    m = rm()
    m.open_position("A", 100.0, 50, 12)
    m.evaluate_exits("A", 130)           # high = 130, no TP1 yet
    assert m.evaluate_exits("A", 110) == []   # -15% from high but trailing inactive, stop not hit


def test_circuit_breaker_and_day_roll():
    m = rm(1000)
    m.open_position("A", 100.0, 250, 12)
    ex = m.evaluate_exits("A", 80)
    assert ex[0][1].startswith("stop")
    m.apply_exit("A", ex[0][0], 80, ex[0][1])        # -50$ = -5% -> breaker
    assert m.halted
    assert any("circuit breaker" in f for f in m.check_entry("Z", GOOD))
    m._box["d"] = "2026-11-17"                       # next day resets
    assert m.check_entry("Z", GOOD) == []
    assert m.day_start_capital == 950


def test_process_priorities():
    m = rm()
    m.open_position("A", 100.0, 50, 12)
    d = {"intent": "enter", "token": "Z", "metrics": GOOD,
         "open_positions": [{"token": "A", "price": 85}]}
    out = m.process(d)
    assert out["exits"] and out["entry"] is None     # exits first
    out = m.process({"intent": "enter", "token": "Z", "metrics": GOOD,
                     "open_positions": [{"token": "A", "price": 100}]})
    assert out["entry"] and out["entry"]["token"] == "Z"


def test_ui_gate():
    assert not ui_gate("Withdraw", "", "click", None)[0]
    assert not ui_gate("Buy", "", "click", None)[0]
    assert not ui_gate("amount", "500", "type", None)[0]
    assert ui_gate("Search", "BONK", "type", None)[0]
    assert ui_gate("Trending", "", "click", None)[0]
    pend = {"amount_str": "1.33"}
    ok, val, _ = ui_gate("amount", "500", "type", pend)
    assert ok and val == "1.33"                      # Grok's amount is overridden
    assert ui_gate("Confirm", "", "click", pend)[0]


def test_element_gate():
    from risk import element_gate
    # CSS selector "#x1" passes ui_gate, but the real element is a Buy button -> blocked
    assert ui_gate("#x1", "", "click", None)[0]
    assert not element_gate("Buy now", "click", None)[0]
    assert not element_gate("css-9f1 BuyButton", "click", None)[0]       # camelCase class
    assert not element_gate("btn buy_btn", "click", None)[0]              # snake_case class
    assert not element_gate("Acheter 1.33 $", "click", None)[0]
    assert not element_gate("Withdraw funds", "click", {"amount_str": "1"})[0]   # never, even approved
    assert not element_gate("", "click", None)[0]                         # unknown icon: fail-closed
    assert not element_gate("Amount Buy", "type", None)[0]                # input inside a Buy form
    # harmless navigation still works
    assert element_gate("Trending /trending", "click", None)[0]
    assert element_gate("Search tokens search", "type", None)[0]
    assert element_gate("GTA VI GTA6 /t/gta6", "click", None)[0]
    # with an approved trade (live only), trade controls are allowed
    assert element_gate("Confirm", "click", {"amount_str": "1.33"})[0]


def test_holders_proxy_and_red_flags():
    m = rm()
    base = {k: v for k, v in GOOD.items() if k != "top5_holders_pct"}
    assert any("missing" in f for f in m.check_entry("A", base))                 # nothing known -> refused
    assert m.check_entry("A", dict(base, top10_holders_pct=25)) == []            # top10 < 40 => top5 < 40
    assert m.check_entry("A", dict(base, top10_holders_pct=45))                  # cannot conclude -> refused
    assert m.check_entry("A", dict(GOOD, top5_holders_pct=45))
    assert m.check_entry("A", dict(GOOD, red_flags=["Unlocked liquidity"]))      # page warning -> refused
    assert m.check_entry("A", dict(GOOD, red_flags=[])) == []
    # prefilter mode (holders / flags checked later on the page)
    assert m.check_entry("A", base, skip={"holders", "flags"}) == []


def test_ref_is_kept():
    m = rm()
    out = m.process({"intent": "enter", "token": "Z", "metrics": GOOD, "ref": "solana:ADDR"})
    assert out["entry"]["ref"] == "solana:ADDR"
    m.open_position("Z", 1.0, 10, 12, ref="solana:ADDR")
    assert m.positions["Z"].ref == "solana:ADDR"


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
