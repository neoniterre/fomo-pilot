"""Run: python test_scanner.py  (no network, no key). Fixtures come from REAL responses (Nov 17, 2026)."""
import asyncio

from risk import RiskManager, Rules
from scanner import (Dex, PriceHistory, VolumeTracker, group_pairs, metrics_from_group, parse_fomo_list,
                     resolve_token)

# --- real fomo.family/top-movers text (trimmed) ---
TOP_MOVERS = """Top Crypto Gainers
20 assets

Position in this view: 1
BUTTHOLE
BUTTHOLE
$0.000627
24h change:
▲
70.51%
Buy
Market details
Position in this view: 2
GTA VI
GTA6
$0.0169
24h change:
▲
62.36%
Buy
Market details
Position in this view: 3
客服小何 (Customer Service Xiao He)
客服小何
$0.00156
24h change:
▼
18.28%
Buy
Market details

All amounts are in USD."""

# --- real /new text (has a "Created" line, stocks included) ---
NEW = """Position in this view: 1
Apple
AAPL

Created Nov 3, 2026

$352.41
24h change:
▼
1.22%
Buy
Market details
Position in this view: 2
FLOAT
FLOAT

Created Oct 28, 2026

$0.00256
24h change:
▼
8.44%
Buy
Market details
"""

# --- real fomo.family/top-movers text, TABLE layout (desktop, Nov 17, 2026, trimmed) ---
TOP_MOVERS_TABLE = """Top Crypto Gainers
20 assets

Asset prices, 24-hour changes, reported market cap, volume and valuation in USD in the selected view
#
Position in this view
\tAsset ↕\tPrice ↕\t24h change ↓\tMarket cap ↕\t24h volume ↕\tValuation ↕\t
Buy asset

1\t
BUTTHOLE
BUTTHOLE
\t$0.000628\t
▲
70.51%
\t$618.40K\t$99.09K\t$618.40K\tBuy
2\t
GTA VI
GTA6
\t$0.0166\t
▲
60.91%
\t$16.36M\t$9.58M\t$16.36M\tBuy
3\t
Claudia
CLAUDIA
\t$0.00710\t
▼
5.00%
\t$6.71M\t$5.71M\t$6.71M\tBuy

All amounts are in USD."""

# --- real DexScreener /latest/dex/search?q=GTA6 pairs (trimmed to the fields we use) ---
SOL = "4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"
PAIRS = [
    {"chainId": "solana", "dexId": "meteora", "pairAddress": "5AFb", "priceUsd": "0.01677",
     "baseToken": {"address": SOL, "symbol": "GTA6"}, "volume": {"h24": 6620288.66, "h1": 168200.06},
     "priceChange": {"m5": -3.53, "h1": 9.88, "h6": -23.04, "h24": 66.39},
     "liquidity": {"usd": 186894.18}, "marketCap": 16774341, "pairCreatedAt": 1793282181000},
    {"chainId": "bsc", "dexId": "fourmeme", "pairAddress": "0xC3B9", "priceUsd": "0.00002015",
     "baseToken": {"address": "0xC3B9F96c19Af9d66203Dc60547fB2900Ebc54444", "symbol": "GTA6"},
     "volume": {"h24": 5559.33, "h1": 5559.33},
     "priceChange": {"m5": -0.02, "h1": 507, "h6": 507, "h24": 507},
     "marketCap": 20154.97, "pairCreatedAt": 1794905441000},                      # fake: +507%, no liquidity
    {"chainId": "solana", "dexId": "raydium", "pairAddress": "FDam", "priceUsd": "0.01747",
     "baseToken": {"address": SOL, "symbol": "GTA6"}, "volume": {"h24": 965624.42, "h1": 42546},
     "priceChange": {"m5": 2.16, "h1": 10.45, "h6": 19.68, "h24": 76.79},
     "liquidity": {"usd": 534847.5}, "marketCap": 17474782, "pairCreatedAt": 1786023355000},
]
NOW_MS = 1794908700000


def test_parse_fomo_list():
    it = parse_fomo_list(TOP_MOVERS)
    assert [i["symbol"] for i in it] == ["BUTTHOLE", "GTA6", "客服小何"]
    assert it[1]["price"] == 0.0169 and it[1]["change_24h_pct"] == 62.36
    assert it[2]["change_24h_pct"] == -18.28                       # down arrow
    n = parse_fomo_list(NEW)
    assert n[0]["symbol"] == "AAPL" and n[0]["price"] == 352.41 and n[1]["price"] == 0.00256
    assert parse_fomo_list("rien") == [] and parse_fomo_list(None) == []
    one = parse_fomo_list(NEW.split("Position in this view: 2")[0])     # single card
    assert [i["symbol"] for i in one] == ["AAPL"]


def test_parse_fomo_table():
    it = parse_fomo_list(TOP_MOVERS_TABLE)
    assert [i["symbol"] for i in it] == ["BUTTHOLE", "GTA6", "CLAUDIA"]
    assert it[0]["name"] == "BUTTHOLE" and it[1]["name"] == "GTA VI"
    assert it[0]["price"] == 0.000628 and it[1]["price"] == 0.0166   # not the market cap column
    assert it[1]["change_24h_pct"] == 60.91 and it[2]["change_24h_pct"] == -5.0


def test_resolve_ignores_fake_chain():
    g, why = resolve_token("GTA6", 0.0169, PAIRS)
    assert why == "ok" and g["chain"] == "solana" and g["address"] == SOL
    assert abs(g["liq"] - (186894.18 + 534847.5)) < 0.01
    assert g["best"]["pairAddress"] == "FDam"                       # biggest pool
    # fomo price far from the on-chain price -> not the same token
    assert resolve_token("GTA6", 0.05, PAIRS)[0] is None
    assert resolve_token("GTA6", None, PAIRS)[1] == "prix fomo illisible"
    assert resolve_token("NOPE", 1.0, PAIRS)[1] == "introuvable"
    assert resolve_token("AAPL", 352.41, [])[1] == "introuvable"     # stocks: no DEX pair


def test_ambiguous_is_refused():
    twin = {"chainId": "base", "pairAddress": "X", "priceUsd": "0.0169",
            "baseToken": {"address": "0xTWIN", "symbol": "GTA6"}, "liquidity": {"usd": 600000},
            "volume": {"h24": 1}, "priceChange": {"h1": 1}, "pairCreatedAt": 1}
    g, why = resolve_token("GTA6", 0.0172, PAIRS + [twin])
    assert g is None and why == "ambigu"


def test_metrics():
    g, _ = resolve_token("GTA6", 0.0169, PAIRS)
    m = metrics_from_group(g, -1.2, now_ms=NOW_MS)
    expected = (0.01677 * 186894.18 + 0.01747 * 534847.5) / (186894.18 + 534847.5)
    assert abs(m["price"] - expected) < 1e-9                         # liquidity-weighted, not "biggest pool"
    assert m["market_cap"] == 17474782 and m["change_1h_pct"] == 10.45
    assert abs(m["volume_24h"] - 7585913.08) < 0.01 and m["liquidity_usd"] == 534847.5
    assert abs(m["age_hours"] - 2468.1) < 0.2                       # oldest pair of the token
    assert m["change_30m_pct"] is None and m["btc_change_1h_pct"] == -1.2
    # missing market cap stays None (no fdv fallback)
    p2 = [dict(p) for p in PAIRS]
    for p in p2:
        p.pop("marketCap", None)
    g2, _ = resolve_token("GTA6", 0.0169, p2)
    assert metrics_from_group(g2, 0, now_ms=NOW_MS)["market_cap"] is None


def test_prefilter_with_risk_rules():
    rm = RiskManager(Rules(), 1000, state_path=None, trade_log=None)
    g, _ = resolve_token("GTA6", 0.0169, PAIRS)
    m = metrics_from_group(g, -1.0, now_ms=NOW_MS)
    fails = rm.check_entry("GTA6", m, skip={"holders", "flags"})
    # real data: +10% in 1h and liquidity only 3% of market cap -> both rules refuse
    assert any("momentum" in f for f in fails) and any("liquidity/market cap" in f for f in fails)
    good = dict(m, change_1h_pct=60, liquidity_usd=2_000_000)
    assert rm.check_entry("GTA6", good, skip={"holders", "flags"}) == []
    assert rm.check_entry("GTA6", good)                              # holders still unknown -> refused
    final = dict(good, top10_holders_pct=25, red_flags=[])
    assert rm.check_entry("GTA6", final) == []
    assert rm.check_entry("GTA6", dict(final, btc_change_1h_pct=None))   # BTC unreadable -> refused


def test_dex_client_errors_are_safe():
    class Broken(Dex):
        async def _get(self, path, params=None):
            raise RuntimeError("429")
    d = Broken()
    assert asyncio.run(d.search("X")) == [] and d.errors == 1

    class Fake(Dex):
        async def _get(self, path, params=None):
            return {"pairs": PAIRS}
    pairs = asyncio.run(Fake().token_pairs(SOL, chain="solana"))
    assert len(pairs) == 2 and all(p["chainId"] == "solana" for p in pairs)


def test_volume_tracker():
    t = VolumeTracker()
    assert t.update("A", 100_000, now=0) is None                    # no old sample yet
    assert t.update("A", 90_000, now=1800) is None
    assert t.update("A", 30_000, now=3600) == 70.0                  # 100k -> 30k over ~1h
    assert t.update("A", 95_000, now=3700) == 5.0
    assert t.update("B", None, now=0) is None


def test_price_history_30m():
    h = PriceHistory()
    assert h.change_pct("A", 1.25, now=100) is None                  # no sample yet -> None (fail-closed)
    h.add("A", 1.0, now=0)
    h.add("A", 1.1, now=900)
    assert h.change_pct("A", 1.25, now=900) is None                  # nothing ~30 min old yet
    assert not h.ready("A", now=900)
    assert h.change_pct("A", 1.25, now=1800) == 25.0                 # sample from t=0 is exactly 30 min old
    assert h.ready("A", now=1800)
    assert h.change_pct("A", 1.25, now=1800 + 240) == 25.0           # tolerance +/- 5 min
    assert h.change_pct("A", 1.25, now=1800 + 400) is None           # too old -> None
    assert h.change_pct("A", 0, now=1800) is None and h.change_pct("B", 1.0, now=1800) is None
    h.add("A", None, now=2000); h.add("A", -1, now=2000)             # garbage ignored
    assert len(h.h["A"]) == 2


def test_30m_rule_end_to_end():
    from risk import RiskManager, Rules
    rm = RiskManager(Rules(use_30m=True), 1000, state_path=None, trade_log=None)
    g, _ = resolve_token("GTA6", 0.0169, PAIRS)
    m = metrics_from_group(g, -1.0, now_ms=NOW_MS)
    m.update(liquidity_usd=2_000_000, change_1h_pct=12)               # 1h weak
    # no history yet -> change_30m None -> refused (never guessed)
    assert any("missing" in f for f in rm.check_entry("GTA6", m, skip={"holders", "flags"}))
    m["change_30m_pct"] = 22.0                                         # +22% in 30m: desk rule satisfied
    assert rm.check_entry("GTA6", m, skip={"holders", "flags"}) == []
    m["change_30m_pct"] = 8.0
    assert any("momentum" in f for f in rm.check_entry("GTA6", m, skip={"holders", "flags"}))
    # thresholds can be tuned from the CLI
    loose = RiskManager(Rules(use_30m=True, min_change_30m=10, min_change_1h=30), 1000, state_path=None, trade_log=None)
    m["change_30m_pct"] = 12.0
    assert loose.check_entry("GTA6", m, skip={"holders", "flags"}) == []


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
