"""
security.py : top holders + red flags from free, keyless security APIs (cloud mode, no Chrome).

  Solana -> RugCheck   GET https://api.rugcheck.xyz/v1/tokens/{mint}/report
  EVM    -> GoPlus     GET https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={addr}

check_token(chain, address) -> {"top5_holders_pct", "top10_holders_pct", "red_flags": [...], "warnings": [...],
                                "source", "ok": bool}
Fail-closed everywhere and NEVER raises: any error -> ok=False, holders None,
red_flags = ["donnée sécurité indisponible"] -> risk.py refuses the entry.

Choices made where docs/SPEC_CLOUD.md left room (always the most cautious option):
  - RugCheck: a top holder whose `address` or `owner` equals a market's `pubkey`, `liquidityAAccount` or
    `liquidityBAccount` is a pool and is excluded (SPEC_CLOUD lot 2). `markets` missing / unreadable -> nothing
    excluded (raw sum, cautious), noted in `source`.
  - RugCheck: freezeAuthority / mintAuthority = null -> no authority, no flag (real answer). Key ABSENT, or
    rugged / risks / topHolders missing -> flag or ok=False (unknown is treated as bad). `warn` risks do not block (spec), they go to `warnings`.
  - GoPlus: every holder counted (contracts and locked included) except addresses listed as DEX pairs.
  - GoPlus: honeypot / buy_tax / sell_tax unknown -> flag; is_open_source == "0" -> flag (GoPlus cannot
    analyse an unverified contract); is_mintable == "1" -> flag, no stablecoin exception (memecoins only).
  - top10 needs 10 holders (top5 needs 5) after exclusions, else None: a partial sum would under-estimate.
  - Unknown chain, empty GoPlus result (token unknown), code != 1, broken JSON, HTTP error after one retry
    on 429, timeout -> ok=False.
"""
from __future__ import annotations

import asyncio
import time

UNAVAILABLE = "donnée sécurité indisponible"

GOPLUS_CHAINS = {"ethereum": "1", "bsc": "56", "base": "8453", "arbitrum": "42161", "polygon": "137"}
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
GOPLUS_URL = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
MAX_TAX = 0.10            # fraction (GoPlus unit)


class SecurityError(Exception):
    """Internal: turned into ok=False by check_token, never escapes."""


def _num(x):
    if x is None or isinstance(x, bool) or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _top(pcts: list, n: int):
    """Sum of the n first percentages, or None if fewer than n or any value unreadable / out of range."""
    if len(pcts) < n:
        return None
    vals = pcts[:n]
    if any(v is None or v < 0 or v > 100 for v in vals):
        return None
    s = round(sum(vals), 2)
    return s if s <= 100.0001 else None


def unavailable(source: str) -> dict:
    return {"top5_holders_pct": None, "top10_holders_pct": None, "red_flags": [UNAVAILABLE],
            "warnings": [], "source": source, "ok": False}


# --------------------------------------------------------------------------- parsers (pure, tested)
def parse_rugcheck(d) -> dict:
    if not isinstance(d, dict):
        raise SecurityError("rugcheck: réponse non JSON objet")
    holders, risks = d.get("topHolders"), d.get("risks")
    if not isinstance(holders, list) or not isinstance(risks, list):
        raise SecurityError("rugcheck: topHolders ou risks absent")

    pools, pools_known = _rugcheck_pool_accounts(d.get("markets"))
    kept = [h for h in holders
            if not (isinstance(h, dict) and ({str(h.get("address") or ""), str(h.get("owner") or "")} & pools))]
    excluded = len(holders) - len(kept)
    pcts = [_num(h.get("pct")) if isinstance(h, dict) else None for h in kept]
    flags, warnings = [], []

    rugged = d.get("rugged")
    if rugged is True:
        flags.append("rugged")
    elif rugged is not False:
        flags.append("statut rugged inconnu")
    for r in risks:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "risque sans nom")
        level = str(r.get("level") or "").lower()
        if level == "danger":
            flags.append("danger: " + name)
        elif level:
            warnings.append(f"{level}: {name}")
    # null (present, value None) = no authority = OK (real RugCheck answer). Absent key = unknown = flag.
    for key, label in (("freezeAuthority", "freeze authority active"), ("mintAuthority", "mint authority active")):
        if key not in d:
            flags.append(label.replace("active", "inconnue"))
        elif d[key] not in (None, "", False):
            flags.append(label)
    insiders = sum(1 for h in holders if isinstance(h, dict) and h.get("insider") is True)
    if insiders:
        flags.append(f"{insiders} holder(s) insider dans le top")

    if not pools_known:
        src = "rugcheck (markets illisibles : calcul brut, pools inclus)"
    elif excluded:
        src = f"rugcheck ({excluded} compte(s) de pool exclu(s))"
    else:
        src = "rugcheck (aucun pool dans le top)"
    return {"top5_holders_pct": _top(pcts, 5), "top10_holders_pct": _top(pcts, 10), "red_flags": flags,
            "warnings": warnings, "source": src, "ok": True, "score": _num(d.get("score_normalised"))}


POOL_FIELDS = ("pubkey", "liquidityAAccount", "liquidityBAccount")


def _rugcheck_pool_accounts(markets):
    """Accounts that belong to a pool (market pubkey + its two token vaults). Returns (set, known).
    known=False when `markets` is missing / not a list: then nothing is excluded (raw sum, cautious)."""
    if not isinstance(markets, list):
        return set(), False
    accounts = set()
    for m in markets:
        if isinstance(m, dict):
            for f in POOL_FIELDS:
                v = m.get(f)
                if isinstance(v, str) and v.strip():
                    accounts.add(v.strip())
    return accounts, True


def parse_goplus(d, address: str) -> dict:
    if not isinstance(d, dict):
        raise SecurityError("goplus: réponse non JSON objet")
    if d.get("code") != 1:
        raise SecurityError(f"goplus: code {d.get('code')} {str(d.get('message'))[:60]}")
    res = (d.get("result") or {}).get(address.lower())
    if not isinstance(res, dict) or not res:
        raise SecurityError("goplus: token inconnu (résultat vide)")
    holders = res.get("holders")
    if not isinstance(holders, list):
        raise SecurityError("goplus: holders absent")

    pools = {str(x.get("pair") or "").lower() for x in (res.get("dex") or []) if isinstance(x, dict)}
    pools.discard("")
    kept = [h for h in holders if isinstance(h, dict) and str(h.get("address") or "").lower() not in pools]
    pcts = [(_num(h.get("percent")) * 100) if _num(h.get("percent")) is not None else None for h in kept]

    flags = []
    yes = lambda k: str(res.get(k)) == "1"
    hp = res.get("is_honeypot")
    if hp is None or hp == "":
        flags.append("honeypot inconnu")
    elif str(hp) == "1":
        flags.append("honeypot")
    for k in ("buy_tax", "sell_tax"):
        t = _num(res.get(k))
        if t is None:
            flags.append(f"{k} inconnue")
        elif t > MAX_TAX:
            flags.append(f"{k} {t * 100:.0f}%")
    for k, label in (("cannot_sell_all", "impossible de tout vendre"), ("hidden_owner", "propriétaire caché"),
                     ("is_blacklisted", "blacklist"), ("can_take_back_ownership", "reprise de propriété possible"),
                     ("transfer_pausable", "transferts suspendables"), ("is_mintable", "mintable")):
        if yes(k):
            flags.append(label)
    if str(res.get("is_open_source")) == "0":
        flags.append("contrat non vérifié")

    src = "goplus" + (f" ({len(holders) - len(kept)} pool(s) DEX exclu(s))" if len(kept) < len(holders) else "")
    return {"top5_holders_pct": _top(pcts, 5), "top10_holders_pct": _top(pcts, 10), "red_flags": flags,
            "warnings": [], "source": src, "ok": True}


# --------------------------------------------------------------------------- HTTP
class SecurityChecker:
    def __init__(self, min_interval: float = 1.1, timeout: float = 15.0, retry_wait_max: float = 10.0):
        self.min_interval, self.timeout, self.retry_wait_max = min_interval, timeout, retry_wait_max
        self._last = {}
        self._client = None

    async def _sleep(self, s: float):
        await asyncio.sleep(s)

    async def _raw_get(self, url: str, params: dict | None):
        """Returns (status, headers, body_bytes). Overridden in tests."""
        import httpx
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": "fomo-pilot"})
        r = await self._client.get(url, params=params)
        return r.status_code, r.headers, r.content

    async def _get_json(self, host: str, url: str, params: dict | None = None):
        import json
        for attempt in (1, 2):
            wait = self._last.get(host, 0) + self.min_interval - time.time()
            if wait > 0:
                await self._sleep(wait)
            self._last[host] = time.time()
            status, headers, body = await self._raw_get(url, params)
            if status == 429 and attempt == 1:
                ra = _num((headers or {}).get("retry-after"))
                await self._sleep(min(ra if ra is not None else 2.0, self.retry_wait_max))
                continue
            if status != 200:
                raise SecurityError(f"{host}: HTTP {status}")
            try:
                return json.loads(body)
            except Exception:
                raise SecurityError(f"{host}: JSON illisible")
        raise SecurityError(f"{host}: HTTP 429")

    async def check_token(self, chain: str, address: str) -> dict:
        chain = (chain or "").lower()
        try:
            if not address:
                return unavailable("adresse manquante")
            if chain == "solana":
                d = await self._get_json("rugcheck", RUGCHECK_URL.format(mint=address))
                return parse_rugcheck(d)
            if chain in GOPLUS_CHAINS:
                d = await self._get_json("goplus", GOPLUS_URL.format(chain_id=GOPLUS_CHAINS[chain]),
                                         {"contract_addresses": address})
                return parse_goplus(d, address)
            return unavailable(f"chaîne non supportée : {chain or '?'}")
        except SecurityError as e:
            return unavailable(str(e))
        except Exception as e:                     # timeout, DNS, TLS, anything: never raise
            return unavailable(f"{chain}: {type(e).__name__}")


_default = SecurityChecker()


async def check_token(chain: str, address: str) -> dict:
    return await _default.check_token(chain, address)
