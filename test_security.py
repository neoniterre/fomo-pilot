"""Run: python test_security.py  (no network, no key). Fake HTTP only."""
import asyncio
import json
import subprocess
import sys
import types

from security import UNAVAILABLE, SecurityChecker, parse_goplus, parse_rugcheck

# --- RugCheck BONK, REAL response 17/11/2026 (fetched on GitHub Actions, trimmed): docs/fixture_rugcheck_bonk.json
#     (api.rugcheck.xyz is unreachable from the dev PC: TLS certificate not trusted).
import os
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "fixture_rugcheck_bonk.json"),
          encoding="utf-8") as _f:
    RUG_BONK = json.load(_f)


def rug_with_pools(markets="__keep__"):
    """SYNTHETIC memecoin (not observed on BONK): the pool vault holds 62 % of the supply, the pool
    account itself (as owner) 9 %, then ordinary holders. Field names as in the real RugCheck markets."""
    holders = [{"address": "VaultA111", "owner": "AmmAuth1", "pct": 62.0, "insider": False},      # = liquidityAAccount
               {"address": "Acc0002", "owner": "Pool1111", "pct": 9.0, "insider": False},         # owner = pool pubkey
               ] + [{"address": f"Acc{i:04d}", "owner": f"Own{i:04d}", "pct": p, "insider": False}
                    for i, p in enumerate([4.0, 3.0, 2.5, 2.0, 1.5, 1.2, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5], start=3)]
    d = dict(RUG_BONK, topHolders=holders, risks=[])
    d["markets"] = ([{"pubkey": "Pool1111", "marketType": "pump_amm", "liquidityAAccount": "VaultA111",
                      "liquidityBAccount": "VaultB111", "lp": {"lpLockedPct": 100}}]
                    if markets == "__keep__" else markets)
    if markets is None:
        d.pop("markets")
    return d

# --- GoPlus USDT Ethereum, REAL response 17/11/2026 (trimmed to the fields we use). percent = FRACTION.
USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
GP_USDT = {"code": 1, "message": "OK", "result": {USDT.lower(): {
    "buy_tax": "0", "sell_tax": "0", "is_honeypot": "0", "cannot_sell_all": None, "hidden_owner": "0",
    "is_blacklisted": "1", "can_take_back_ownership": "0", "transfer_pausable": "1", "is_mintable": "1",
    "is_open_source": "1", "holder_count": "16029206", "owner_address": "0xc6cde7c39eb2f0f0095f41570af89efc2c1ea828",
    "holders": [
        {"address": "0xf977814e90da44bfa03b6295a0616a897441acec", "is_contract": 0, "percent": "0.166080063982998429", "is_locked": 0},
        {"address": "0x47ac0fb4f2d84898e4d9e7b4dab3c24507a6d503", "is_contract": 0, "percent": "0.108960358753843416", "is_locked": 0},
        {"address": "0x5754284f345afc66a98fbb0a0afe71e0f007b949", "is_contract": 0, "percent": "0.052284258147604752", "is_locked": 0},
        {"address": "0x6c96de32cea08842dcc4058c14d3aaad7fa41dee", "is_contract": 1, "percent": "0.043403995105791840", "is_locked": 0},
        {"address": "0x5a52e96bacdabb82fd05763e25335261b270efcb", "is_contract": 0, "percent": "0.035222267014562828", "is_locked": 0},
        {"address": "0x835678a611b28684005a5e2233695fb6cbbb0007", "is_contract": 0, "percent": "0.026809875059453843", "is_locked": 0},
        {"address": "0xc6cde7c39eb2f0f0095f41570af89efc2c1ea828", "is_contract": 1, "percent": "0.023727016285498391", "is_locked": 0},
        {"address": "0x5227f603c1ee34ce3c06efe6477003bdfccb2f8c", "is_contract": 0, "percent": "0.013944375337446697", "is_locked": 0},
        {"address": "0x98adef6f2ac8572ec48965509d69a8dd5e8bba9d", "is_contract": 0, "percent": "0.007186251414310668", "is_locked": 0},
        {"address": "0xa7c0d36c4698981fab42a7d8c783674c6fe2592d", "is_contract": 0, "percent": "0.006430006195858016", "is_locked": 0},
    ]}}}
GP_EMPTY = {"code": 1, "message": "OK", "result": {}}          # REAL answer for an unknown token


def gp_variant(**changes):
    d = json.loads(json.dumps(GP_USDT))
    d["result"][USDT.lower()].update(changes)
    return d


class FakeChecker(SecurityChecker):
    """Answers from a script: each item is (status, body) or an exception to raise."""

    def __init__(self, script):
        super().__init__(min_interval=0)
        self.script, self.calls, self.slept = list(script), [], []

    async def _sleep(self, s):
        self.slept.append(s)

    async def _raw_get(self, url, params):
        self.calls.append((url, params))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        if not isinstance(body, (bytes, str)):
            body = json.dumps(body)
        return status, {}, body.encode() if isinstance(body, str) else body


def check(script, chain, addr):
    fc = FakeChecker(script)
    return asyncio.run(fc.check_token(chain, addr)), fc


# ------------------------------------------------------------------------------------------- RugCheck
def test_rugcheck_bonk_holders():
    assert RUG_BONK["freezeAuthority"] is None and RUG_BONK["mintAuthority"] is None   # real answer: null, present
    r = parse_rugcheck(RUG_BONK)
    assert r["ok"] and r["top5_holders_pct"] == 28.55 and r["top10_holders_pct"] == 38.45
    assert r["red_flags"] == []                                     # null authorities, not rugged: no flag
    assert r["warnings"] == ["warn: Mutable metadata"]              # "warn" does not block (spec)
    assert r["source"] == "rugcheck (aucun pool dans le top)" and r["score"] == 7


def test_rugcheck_null_vs_absent_authority():
    f = parse_rugcheck(dict(RUG_BONK, freezeAuthority=None, mintAuthority=""))["red_flags"]
    assert f == []                                                  # null / empty = no authority
    f = parse_rugcheck(dict(RUG_BONK, freezeAuthority="FrZ1"))["red_flags"]
    assert f == ["freeze authority active"]
    d = {k: v for k, v in RUG_BONK.items() if k != "mintAuthority"}
    assert parse_rugcheck(d)["red_flags"] == ["mint authority inconnue"]   # absent = unknown = flag


def test_rugcheck_excludes_identifiable_pools():
    r = parse_rugcheck(rug_with_pools())
    # 62 % vault (address = liquidityAAccount) and 9 % account owned by the pool (owner = pubkey) are excluded
    assert r["top5_holders_pct"] == round(4.0 + 3.0 + 2.5 + 2.0 + 1.5, 2)
    assert r["top10_holders_pct"] == round(4.0 + 3.0 + 2.5 + 2.0 + 1.5 + 1.2 + 1.0 + 0.9 + 0.8 + 0.7, 2)
    assert r["source"] == "rugcheck (2 compte(s) de pool exclu(s))"
    # markets missing or unreadable -> nothing excluded (raw sum, cautious): 62 % pool counted -> refused later
    for markets in (None, "garbage"):
        r = parse_rugcheck(rug_with_pools(markets))
        assert r["top5_holders_pct"] == round(62.0 + 9.0 + 4.0 + 3.0 + 2.5, 2)
        assert "calcul brut" in r["source"]
    # markets present but no usable account field -> nothing excluded either
    r = parse_rugcheck(rug_with_pools([{"marketType": "x", "lp": {}}]))
    assert r["top5_holders_pct"] == round(62.0 + 9.0 + 4.0 + 3.0 + 2.5, 2)


def test_rugcheck_pool_exclusion_keeps_top10_honest():
    d = rug_with_pools()
    d["topHolders"] = d["topHolders"][:11]                          # 11 listed - 2 pools = 9 left
    r = parse_rugcheck(d)
    assert r["top5_holders_pct"] == 13.0 and r["top10_holders_pct"] is None   # no partial top10


def test_rugcheck_red_flags():
    d = dict(RUG_BONK, rugged=True, freezeAuthority="FrZ1", mintAuthority="MnT1",
             risks=[{"name": "Top 10 holders high ownership", "level": "danger"}])
    d["topHolders"] = [dict(h, insider=(i < 2)) for i, h in enumerate(RUG_BONK["topHolders"])]
    f = parse_rugcheck(d)["red_flags"]
    assert "rugged" in f and "danger: Top 10 holders high ownership" in f
    assert "freeze authority active" in f and "mint authority active" in f
    assert "2 holder(s) insider dans le top" in f


def test_rugcheck_unknown_is_bad():
    d = {k: v for k, v in RUG_BONK.items() if k not in ("freezeAuthority", "rugged")}
    f = parse_rugcheck(d)["red_flags"]
    assert "freeze authority inconnue" in f and "statut rugged inconnu" in f
    few = dict(RUG_BONK, topHolders=RUG_BONK["topHolders"][:4])
    assert parse_rugcheck(few)["top5_holders_pct"] is None           # 4 holders: no partial sum
    bad = dict(RUG_BONK, topHolders=[dict(h, pct="??") for h in RUG_BONK["topHolders"]])
    assert parse_rugcheck(bad)["top5_holders_pct"] is None
    r, _ = check([(200, {"risks": []})], "solana", BONK)             # no topHolders at all
    assert r["ok"] is False and r["red_flags"] == [UNAVAILABLE]


def test_rugcheck_via_http_and_429_retry():
    r, fc = check([(429, ""), (200, RUG_BONK)], "solana", BONK)
    assert r["ok"] and r["top5_holders_pct"] == 28.55
    assert len(fc.calls) == 2 and fc.slept and "rugcheck.xyz/v1/tokens/" + BONK in fc.calls[0][0]
    r, fc = check([(429, ""), (429, "")], "solana", BONK)            # only one retry
    assert r["ok"] is False and len(fc.calls) == 2


# ------------------------------------------------------------------------------------------- GoPlus
def test_goplus_usdt_fraction_to_percent():
    r = parse_goplus(GP_USDT, USDT)                                   # mixed-case address on purpose
    assert r["ok"] and r["top5_holders_pct"] == 40.6 and r["top10_holders_pct"] == 48.4
    assert set(r["red_flags"]) == {"blacklist", "transferts suspendables", "mintable"}
    r2, fc = check([(200, GP_USDT)], "ethereum", USDT)
    assert r2 == r and fc.calls[0][0].endswith("/token_security/1")
    assert fc.calls[0][1] == {"contract_addresses": USDT}


def test_goplus_honeypot_and_taxes():
    f = parse_goplus(gp_variant(is_honeypot="1"), USDT)["red_flags"]
    assert "honeypot" in f
    f = parse_goplus(gp_variant(sell_tax="0.25", buy_tax="0.05"), USDT)["red_flags"]
    assert "sell_tax 25%" in f and not any(x.startswith("buy_tax") for x in f)
    f = parse_goplus(gp_variant(sell_tax="", is_honeypot=None), USDT)["red_flags"]
    assert "sell_tax inconnue" in f and "honeypot inconnu" in f      # unknown = bad
    f = parse_goplus(gp_variant(is_open_source="0", hidden_owner="1", cannot_sell_all="1"), USDT)["red_flags"]
    assert {"contrat non vérifié", "propriétaire caché", "impossible de tout vendre"} <= set(f)


def test_goplus_pool_excluded_and_partial_top10():
    pool = GP_USDT["result"][USDT.lower()]["holders"][0]["address"]
    r = parse_goplus(gp_variant(dex=[{"name": "UniswapV2", "pair": pool.upper()}]), USDT)
    assert r["top10_holders_pct"] is None                            # 9 holders left: no partial top10
    assert r["top5_holders_pct"] == round((0.108960358753843416 + 0.052284258147604752 + 0.043403995105791840
                                           + 0.035222267014562828 + 0.026809875059453843) * 100, 2)
    assert "1 pool(s) DEX exclu(s)" in r["source"]


def test_goplus_errors_never_raise():
    for script in ([(200, GP_EMPTY)],                                # unknown token (real answer)
                   [(200, {"code": 2, "message": "rate limited", "result": {}})],
                   [(200, "{not json")],
                   [(500, "boom")],
                   [asyncio.TimeoutError()],
                   [RuntimeError("TLS")]):
        r, _ = check(script, "bsc", USDT)
        assert r["ok"] is False and r["red_flags"] == [UNAVAILABLE]
        assert r["top5_holders_pct"] is None and r["top10_holders_pct"] is None


def test_unknown_chain_no_http():
    for chain in ("tron", "", None):
        r, fc = check([], chain, USDT)
        assert r["ok"] is False and fc.calls == [] and r["red_flags"] == [UNAVAILABLE]
    r, fc = check([], "ethereum", "")
    assert r["ok"] is False and fc.calls == []


# ------------------------------------------------------------------------------------------- risk + pilot
def test_risk_refuses_unavailable_security():
    from risk import RiskManager, Rules
    rm = RiskManager(Rules(), 1000, state_path=None, trade_log=None)
    good = dict(price=1.0, volume_24h=300_000, market_cap=5_000_000, age_hours=2, change_30m_pct=25,
                change_1h_pct=60, liquidity_usd=600_000, btc_change_1h_pct=-1)
    r, _ = check([(500, "")], "solana", BONK)
    m = dict(good, top5_holders_pct=r["top5_holders_pct"], top10_holders_pct=r["top10_holders_pct"],
             red_flags=r["red_flags"])
    assert rm.check_entry("Z", m)                                     # refused
    r = parse_rugcheck(RUG_BONK)
    m = dict(good, top5_holders_pct=r["top5_holders_pct"], top10_holders_pct=r["top10_holders_pct"],
             red_flags=r["red_flags"])
    assert rm.check_entry("Z", m) == []                               # clean BONK-like token passes


def test_pilot_cloud_verify_uses_security_not_chrome():
    import pilot
    from pilot import FomoPilot
    from test_scanner import PAIRS, SOL
    pilot.logger.disabled = True

    class FakeDex:
        async def token_pairs(self, address, chain=None):
            return [p for p in PAIRS if p["chainId"] == chain and p["baseToken"]["address"] == address]

    class FakeBtc:
        async def get(self):
            return -1.0

    class FakeSec:
        def __init__(self, result):
            self.result, self.asked = result, []

        async def check_token(self, chain, address):
            self.asked.append((chain, address))
            return self.result

    class FakeRisk:
        def __init__(self):
            self.decisions = []

        def process(self, d):
            self.decisions.append(d)
            return {"exits": [], "entry": None, "log": []}

    def run(sec_result):
        fp = object.__new__(FomoPilot)
        fp.cloud, fp.dex, fp.btc, fp.cooldown = True, FakeDex(), FakeBtc(), {}
        fp.hist = types.SimpleNamespace(change_pct=lambda key, price, now=None: None)
        fp.security, fp.risk = FakeSec(sec_result), FakeRisk()
        fp.target = {"symbol": "GTA6", "chain": "solana", "address": SOL, "ttl": 6}
        fp.take_snapshot = None                                       # would crash if Chrome were used

        async def no_plan(plan):
            return None
        fp.handle_plan = no_plan
        asyncio.run(fp.verify_target_cloud())
        return fp

    fp = run({"ok": False, "top5_holders_pct": 12.0, "top10_holders_pct": 20.0, "red_flags": [UNAVAILABLE],
              "source": "rugcheck: HTTP 500"})
    m = fp.risk.decisions[0]["metrics"]
    assert fp.security.asked == [("solana", SOL)] and fp.target is None
    assert m["top5_holders_pct"] is None and m["top10_holders_pct"] is None   # failed check never trusted
    assert m["red_flags"] == [UNAVAILABLE] and m["price"] > 0
    fp = run(parse_rugcheck(RUG_BONK))
    m = fp.risk.decisions[0]["metrics"]
    assert m["top5_holders_pct"] == 28.55 and m["red_flags"] == []
    assert fp.risk.decisions[0]["ref"] == "solana:" + SOL


def test_cli_cloud_refuses_live_and_needs_auto():
    for extra, msg in ((["--auto", "--cloud", "--live"], "paper seulement"),
                       (["--auto", "--cloud", "--auto-entry"], "paper seulement"),
                       (["--cloud"], "qu'avec --auto")):
        p = subprocess.run([sys.executable, "pilot.py", *extra], capture_output=True, timeout=60,
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "NTFY_TOPIC": ""})
        out = p.stdout.decode("utf-8", "replace")
        assert p.returncode == 1 and msg in out, (extra, p.returncode, out[-200:])


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
