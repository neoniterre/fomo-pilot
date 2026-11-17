"""Run: python test_reader.py  (no network, no key)"""
import asyncio, json
from reader import parse_number, parse_age_hours, extract_metrics, extract_token, TextVision

def test_numbers():
    assert parse_number("$1.2M") == 1_200_000
    assert parse_number("312K") == 312_000
    assert parse_number("1,234.5") == 1234.5
    assert parse_number("12,5") == 12.5
    assert parse_number("-8.4") == -8.4
    assert parse_number("abc") is None and parse_number(None) is None

def test_age():
    assert parse_age_hours("2h 15m") == 2.25
    assert parse_age_hours("3d") == 72
    assert parse_age_hours("1d 4h") == 28
    assert parse_age_hours("soon") is None

SAMPLE = """$BONK Pump
Price $0.0123
Market Cap
$5.2M
Liquidity: $610K
Volume 24h $312K
Top 5 holders 31.5%
Age 2h 15m
30m +25.4%
1h +62%
24h -3%
"""

def test_extract():
    m = extract_metrics(SAMPLE)
    assert m["price"] == 0.0123 and m["market_cap"] == 5_200_000
    assert m["liquidity_usd"] == 610_000 and m["volume_24h"] == 312_000
    assert m["top5_holders_pct"] == 31.5 and m["age_hours"] == 2.25
    assert m["change_30m_pct"] == 25.4 and m["change_1h_pct"] == 62.0   # 24h not mistaken for 1h
    assert extract_token("", "https://x/y/abc", SAMPLE) == "BONK"

def test_missing_is_none():
    m = extract_metrics("Price $1\nVolume $500K")
    assert m["top5_holders_pct"] is None and m["market_cap"] is None   # never guessed

def test_provider_and_risk_end_to_end():
    from risk import RiskManager, Rules
    tv = TextVision()
    async def fake_btc(): return -1.0
    tv.btc.get = fake_btc
    ui = {"url": "https://fomo.family/t/bonk", "title": "$BONK", "visible_text": SAMPLE}
    d = json.loads(asyncio.run(tv.ask("", "UI Snapshot:\n" + json.dumps(ui))))
    assert d["intent"] == "enter" and d["token"] == "BONK"
    rm = RiskManager(Rules(), 1000, state_path=None, trade_log=None)
    out = rm.process(d)
    assert out["entry"] and out["entry"]["token"] == "BONK"
    # a metric the page does not show -> entry refused
    ui["visible_text"] = SAMPLE.replace("Top 5 holders 31.5%", "")
    d = json.loads(asyncio.run(tv.ask("", "UI Snapshot:\n" + json.dumps(ui))))
    assert rm.process(d)["entry"] is None

if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
