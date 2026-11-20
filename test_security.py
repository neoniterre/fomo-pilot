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


def _fixture(name):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", name), encoding="utf-8") as f:
        return json.load(f)


# --- REAL RugCheck answers with the pool in the top holders (GitHub Actions, 17/11/2026, 10 holders kept).
#     liquidityAAccount / liquidityBAccount are OBJECTS {owner, mint, ...}.
RUG_PUMPFUN = _fixture("fixture_rugcheck_pool_pumpfun.json")     # ADA, pump_fun curve = 82.67 %
RUG_RAYDIUM = _fixture("fixture_rugcheck_pool_raydium.json")     # OGS, raydium_cpmm pool = 26.36 %


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


def test_rugcheck_real_pools_top5():
    """SPEC_CLOUD §6: top5 without the pool = 7.36 (pump_fun), 12.38 (raydium_cpmm), 28.55 (BONK, no pool)."""
    for fixture, top5, raw_top5 in ((RUG_PUMPFUN, 7.36, 89.15), (RUG_RAYDIUM, 12.38, 36.58), (RUG_BONK, 28.55, 28.55)):
        r = parse_rugcheck(fixture)
        assert r["ok"] and r["top5_holders_pct"] == top5, (fixture.get("mint"), r)
        assert r["red_flags"] == []
        raw = parse_rugcheck({k: v for k, v in fixture.items() if k != "markets"})   # markets unreadable
        assert raw["top5_holders_pct"] == raw_top5 and "calcul brut" in raw["source"]
    for fixture in (RUG_PUMPFUN, RUG_RAYDIUM):
        r = parse_rugcheck(fixture)
        assert r["source"] == "rugcheck (1 compte(s) de pool exclu(s))"
        assert r["top10_holders_pct"] is None          # 10 kept in the fixture - 1 pool = 9: no partial top10
    assert isinstance(RUG_PUMPFUN["markets"][0]["liquidityAAccount"], dict)   # objects, not strings


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


def test_cloud_never_live_cli_and_workflows():
    """Guard rail: pilot.py refuses --live with --cloud, and NO GitHub workflow can start the bot live
    (bot-cloud.yml first; every other workflow too, cautious choice)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NTFY_TOPIC": ""}
    p = subprocess.run([sys.executable, "pilot.py", "--auto", "--cloud", "--live"], capture_output=True,
                       timeout=60, env=env)
    assert p.returncode == 1 and "paper seulement" in p.stdout.decode("utf-8", "replace")

    wf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github", "workflows")
    bot = open(os.path.join(wf_dir, "bot-cloud.yml"), encoding="utf-8").read()
    assert "pilot.py --auto --cloud" in bot                        # the run line we guard is really there
    for name in sorted(os.listdir(wf_dir)):
        if name.endswith((".yml", ".yaml")):
            txt = open(os.path.join(wf_dir, name), encoding="utf-8").read()
            assert "--live" not in txt and "--auto-entry" not in txt, name


def test_bot_workflows_install_pinned_requirements():
    """The workflows that RUN the bot install the exact versions of requirements.txt (a silent package
    update must not change the cloud bot), and requirements.txt pins every package with ==."""
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("bot-cloud.yml", "cloud-test.yml", "bot-test.yml", "bot-test2.yml"):
        txt = open(os.path.join(here, ".github", "workflows", name), encoding="utf-8").read()
        installs = [l.strip() for l in txt.splitlines() if "pip install" in l]
        assert installs and all("pip install -r requirements.txt" in l for l in installs), (name, installs)
    reqs = [l.split("#")[0].strip() for l in open(os.path.join(here, "requirements.txt"), encoding="utf-8")]
    reqs = [r for r in reqs if r]
    assert reqs and all("==" in r for r in reqs), reqs
    names = {r.split("==")[0].lower() for r in reqs}
    assert {"httpx", "playwright", "python-dotenv"} <= names        # what the cloud bot needs


def _workflow_steps(txt):
    """{step name: step text} for a GitHub workflow (simple text split on '- name:', no YAML lib needed)."""
    steps, cur = {}, None
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("- name:"):
            cur = s[len("- name:"):].strip()
            steps[cur] = []
        elif s.startswith("- uses:"):
            cur = None
        elif cur:
            steps[cur].append(line)
    return {k: "\n".join(v) for k, v in steps.items()}


def _if_line(step_text):
    return next((l.strip()[3:].strip() for l in step_text.splitlines() if l.strip().startswith("if:")), "")


def test_bot_cloud_no_relaunch_loop_on_quick_crash():
    """R1 (docs/ACCORD.md): a bot that dies in < 10 min (or never starts) must NOT relaunch the chain;
    it sends a priority-5 ntfy alert and lets the cron retry. A requested short run is neither relaunched nor alerted."""
    here = os.path.dirname(os.path.abspath(__file__))
    steps = _workflow_steps(open(os.path.join(here, ".github", "workflows", "bot-cloud.yml"), encoding="utf-8").read())
    bot = steps["Bot (PAPER, --cloud)"]
    assert "START=$(date +%s)" in bot and "DURATION=$(( $(date +%s) - START ))" in bot
    assert "MIN_RUN_SECONDS=600" in bot and '"$DURATION" -ge "$MIN_RUN_SECONDS"' in bot
    assert 'echo "LONG_RUN=1" >> "$GITHUB_ENV"' in bot
    assert bot.index("START=$(date +%s)") < bot.index("python pilot.py --auto --cloud") < bot.index("DURATION=")

    relaunch = _if_line(steps["Relance de la chaîne"])
    assert "env.LONG_RUN == '1'" in relaunch                         # fail-closed: no LONG_RUN -> no relaunch
    assert "github.event.inputs.chain != 'false'" in relaunch and "env.STOPPED != '1'" in relaunch
    assert "gh workflow run bot-cloud.yml" in steps["Relance de la chaîne"]

    quick = steps["Arrêt rapide (plantage au démarrage)"]
    q_if = _if_line(quick)
    assert q_if.startswith("always()") and "env.LONG_RUN != '1'" in q_if          # also when the bot never ran
    assert "env.SHORT_REQUESTED != '1'" in q_if and "github.event.inputs.chain != 'false'" in q_if
    assert "Priority: 5" in quick and "plante au d" in quick and "gh workflow run" not in quick
    assert "secrets.NTFY_TOPIC" in quick and "ntfy.sh/$NTFY_TOPIC" in quick
    names = list(steps)
    assert names.index("Arrêt rapide (plantage au démarrage)") < names.index("Relance de la chaîne")


def _wf(name):
    here = os.path.dirname(os.path.abspath(__file__))
    return open(os.path.join(here, ".github", "workflows", name), encoding="utf-8").read()


def test_all_workflows_are_valid_yaml():
    """Every .github/workflows/*.yml must load with yaml.safe_load. 18/11/2026: bot-test.yml had `run: echo "... : ..."`
    (a ': ' inside a plain scalar) -> invalid YAML, rejected by GitHub, while all the text-based tests were green."""
    try:
        import yaml
    except ImportError:
        raise AssertionError("PyYAML manquant : pip install -r requirements.txt "
                             "(Python 3.15 Windows : PYYAML_FORCE_LIBYAML=0)")
    wf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github", "workflows")
    names = sorted(n for n in os.listdir(wf_dir) if n.endswith((".yml", ".yaml")))
    assert {"bot-cloud.yml", "bot-test.yml", "tests.yml"} <= set(names), names
    for name in names:
        with open(os.path.join(wf_dir, name), encoding="utf-8") as f:
            try:
                d = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise AssertionError(f"{name} : YAML invalide : {e}")
        assert isinstance(d, dict) and isinstance(d.get("jobs"), dict) and d["jobs"], name
        assert (True in d) or ("on" in d), name            # YAML 1.1 reads the `on:` key as True
        for job, spec in d["jobs"].items():
            steps = spec.get("steps") or []
            assert steps and all(isinstance(s, dict) and ("run" in s or "uses" in s) for s in steps), (name, job)


def test_bot_test_is_isolated_from_the_real_bot():
    """ACCORD bot-test: the test bot never touches the real books (branch `data`, state.json, trades.jsonl),
    sends no ntfy alert, has no cron, stops by itself after `days` (default 7) and keeps the R1 guard."""
    import re
    txt = _wf("bot-test.yml")
    pushes = re.findall(r"HEAD:([\w-]+)", txt)
    assert pushes and set(pushes) == {"data-test"}, pushes                     # only ever pushes data-test
    assert not re.search(r"origin/data\b(?!-)|heads origin data\b(?!-)|fetch origin data\b(?!-)", txt)
    assert not re.search(r"(?<![\w-])state\.json|(?<![\w-])trades\.jsonl", txt)  # only state_test / trades_test
    assert "--state-file state_test.json --trade-log trades_test.jsonl" in txt
    assert "--gap-buffer-pct 8 --exit-slippage-pct 1" in txt and "--capital 30" in txt
    assert "secrets." not in txt and "NTFY_TOPIC" not in txt and "ntfy.sh" not in txt   # no alert, no secret
    assert "schedule:" not in txt
    assert 'default: "7"' in txt and "TEST_UNTIL" in txt and "group: bot-test" in txt
    steps = _workflow_steps(txt)
    relaunch = _if_line(steps["Relance de la chaîne"])
    assert "env.LONG_RUN == '1'" in relaunch and "gh workflow run bot-test.yml" in steps["Relance de la chaîne"]
    assert "env.LONG_RUN != '1'" in _if_line(steps["Arrêt rapide (plantage au démarrage)"])
    bot = next(v for k, v in steps.items() if k.startswith("Bot TEST"))
    assert "MIN_RUN_SECONDS=600" in bot and 'echo "LONG_RUN=1" >> "$GITHUB_ENV"' in bot


def test_bot_cloud_never_uses_test_options_and_saves_the_trace():
    txt = _wf("bot-cloud.yml")
    for word in ("--gap-buffer-pct", "--exit-slippage-pct", "--trade-log", "state_test", "trades_test", "data-test"):
        assert word not in txt, word
    loops = [l for l in txt.splitlines() if l.strip().startswith("for f in ")]
    assert len(loops) == 2 and all("position_trace.jsonl" in l for l in loops), loops   # restore AND save()


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
