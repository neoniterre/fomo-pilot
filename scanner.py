"""
scanner.py : candidates + exact numbers, with plain code (no LLM, no API cost).

  1. parse_fomo_list : reads fomo's public lists (e.g. /top-movers) from the page text.
  2. Dex             : DexScreener public API (no key, ~300 req/min).
  3. resolve_token   : maps a fomo symbol to ONE on-chain token. Symbols are NOT unique
                       (e.g. a fake "GTA6" on another chain with +500% and no liquidity),
                       so we match on liquidity AND on price vs the fomo price, and refuse
                       when it is ambiguous.
  4. metrics_from_group : the numbers risk.py needs (age from pairCreatedAt, 1h change, ...).

Fail-closed everywhere: anything unreadable becomes None and risk.py refuses the entry.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

from reader import parse_number

BLOCK = re.compile(r"Position in this view:\s*\d+")
PRICE_LINE = re.compile(r"^\$[\d.,]+[KMBkmb]?$")
TABLE_START = re.compile(r"^buy asset$", re.IGNORECASE)


# --------------------------------------------------------------------------- fomo lists
def _parse_block(lines: list[str]) -> dict | None:
    """One token: [name, symbol, ..., $price, ..., ▲/▼, pct%, ...] -> item, or None."""
    if len(lines) < 4:
        return None
    price, change = None, None
    for i, l in enumerate(lines):
        if price is None and PRICE_LINE.match(l):
            price = parse_number(l)
        if change is None and l in ("▲", "▼") and i + 1 < len(lines):
            v = parse_number(lines[i + 1].replace("%", ""))
            if v is not None:
                change = -v if l == "▼" else v
    return {"name": lines[0], "symbol": lines[1], "price": price, "change_24h_pct": change}


def _clean_lines(text: str) -> list[str]:
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def parse_fomo_list(text: str) -> list[dict]:
    """fomo.family/top-movers, /new ... -> [{name, symbol, price, change_24h_pct}]

    Two layouts exist:
      - cards: one "Position in this view: N" before each token (mobile / older layout)
      - table: the label appears once in the header, then each row starts with its rank
        on its own line ("1", "2", ...) after the "Buy asset" header cell.
    """
    blocks = BLOCK.split(text or "")
    if len(blocks) > 2:  # card layout: the label repeats for each token
        return [it for b in blocks[1:] if (it := _parse_block(_clean_lines(b)))]

    lines = _clean_lines(text)
    start = next((i + 1 for i, l in enumerate(lines) if TABLE_START.match(l)), 0)
    rows, cur, expected = [], None, 1
    for l in lines[start:]:
        if l == str(expected):          # next rank: a new row starts
            if cur is not None:
                rows.append(cur)
            cur, expected = [], expected + 1
        elif cur is not None:
            cur.append(l)
    if cur is not None:
        rows.append(cur)
    items = [it for r in rows if (it := _parse_block(r))]
    if not items and len(blocks) == 2:  # card layout with a single token
        items = [it for it in [_parse_block(_clean_lines(blocks[1]))] if it]
    return items


# --------------------------------------------------------------------------- DexScreener
def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


class Dex:
    BASE = "https://api.dexscreener.com"

    def __init__(self, min_interval: float = 0.3):
        self.min_interval = min_interval
        self._last = 0.0
        self._client = None
        self._lock = None
        self.errors = 0
        self.rate_limited = 0        # number of HTTP 429 seen (the position loop slows down on it)

    async def _get(self, path: str, params: dict | None = None):
        import httpx
        # the scan and the position loop share this client: serialize the pacing, not the requests
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            wait = self._last + self.min_interval - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.time()
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        r = await self._client.get(self.BASE + path, params=params)
        r.raise_for_status()
        return r.json()

    def _failed(self, e: Exception):
        self.errors += 1
        if getattr(getattr(e, "response", None), "status_code", None) == 429:
            self.rate_limited += 1

    async def search(self, query: str) -> list[dict]:
        try:
            return (await self._get("/latest/dex/search", {"q": query})).get("pairs") or []
        except Exception as e:
            self._failed(e)
            return []

    async def token_pairs(self, address: str, chain: str | None = None) -> list[dict]:
        try:
            pairs = (await self._get(f"/latest/dex/tokens/{address}")).get("pairs") or []
        except Exception as e:
            self._failed(e)
            return []
        if chain:
            pairs = [p for p in pairs if p.get("chainId") == chain]
        return [p for p in pairs if (p.get("baseToken") or {}).get("address") == address]


def _liq(p):
    return _num((p.get("liquidity") or {}).get("usd")) or 0.0


def group_pairs(pairs: list[dict], symbol: str | None = None) -> list[dict]:
    """Groups pairs by (chain, base token address). Pairs without liquidity or price are ignored."""
    groups = {}
    for p in pairs or []:
        b = p.get("baseToken") or {}
        if not b.get("address"):
            continue
        if symbol and (b.get("symbol") or "").upper() != symbol.upper():
            continue
        price = _num(p.get("priceUsd"))
        if _liq(p) <= 0 or not price or price <= 0:
            continue
        key = (p.get("chainId"), b["address"])
        g = groups.setdefault(key, {"chain": p.get("chainId"), "address": b["address"],
                                    "symbol": b.get("symbol"), "pairs": [], "liq": 0.0})
        g["pairs"].append(p)
        g["liq"] += _liq(p)
    for g in groups.values():
        g["best"] = max(g["pairs"], key=_liq)
    return list(groups.values())


def resolve_token(symbol: str, fomo_price, pairs: list[dict], price_tol: float = 0.10,
                  dominance: float = 3.0):
    """Returns (group, "ok") or (None, reason). Refuses when in doubt."""
    fp = _num(fomo_price)
    if not fp or fp <= 0:
        return None, "prix fomo illisible"
    groups = group_pairs(pairs, symbol)
    if not groups:
        return None, "introuvable"
    ok = [g for g in groups if abs(_num(g["best"]["priceUsd"]) / fp - 1) <= price_tol]
    if not ok:
        return None, "prix différent"
    ok.sort(key=lambda g: -g["liq"])
    if len(ok) > 1 and ok[0]["liq"] < dominance * ok[1]["liq"]:
        return None, "ambigu"
    return ok[0], "ok"


def _sum_path(pairs, key, sub):
    vals = [_num((p.get(key) or {}).get(sub)) for p in pairs]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def metrics_from_group(g: dict, btc_1h, now_ms: float | None = None) -> dict:
    """Numbers for risk.py. change_30m is not provided by the source (option B: 1h only)."""
    best, pairs = g["best"], g["pairs"]
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    created = [_num(p.get("pairCreatedAt")) for p in pairs]
    created = [c for c in created if c]
    age = max((now_ms - min(created)) / 3_600_000, 0.0) if created else None
    # price = liquidity-weighted average over the token's pools: stable, no jumping between pools
    wsum = sum(_liq(p) for p in pairs)
    price = sum(_num(p.get("priceUsd")) * _liq(p) for p in pairs) / wsum if wsum else None
    return {
        "price": price,
        "volume_24h": _sum_path(pairs, "volume", "h24"),
        "volume_h1": _sum_path(pairs, "volume", "h1"),
        "market_cap": _num(best.get("marketCap")),          # no fdv fallback: fail-closed
        "age_hours": round(age, 2) if age is not None else None,
        "change_1h_pct": _num((best.get("priceChange") or {}).get("h1")),
        "change_30m_pct": None,
        "liquidity_usd": _liq(best) or None,                 # biggest pool (conservative)
        "btc_change_1h_pct": btc_1h,
    }


# --------------------------------------------------------------------------- volume drop
class VolumeTracker:
    """Volume drop over ~1h, computed from our own samples (the API only gives the current h1 volume)."""

    def __init__(self, min_age_s: float = 3300, keep_s: float = 10800):
        self.min_age, self.keep, self.hist = min_age_s, keep_s, {}

    def update(self, key: str, vol_h1, now: float | None = None):
        now = time.time() if now is None else now
        h = self.hist.setdefault(key, [])
        if vol_h1 is not None:
            h.append((now, vol_h1))
        self.hist[key] = h = [(t, v) for t, v in h if now - t <= self.keep]
        olds = [v for t, v in h if now - t >= self.min_age]
        if vol_h1 is None or not olds or olds[-1] <= 0:
            return None
        return round((1 - vol_h1 / olds[-1]) * 100, 1)


# --------------------------------------------------------------------------- 30-minute change
class PriceHistory:
    """DexScreener gives 5m / 1h / 6h / 24h but no 30m, so we build it from our own samples.
    change_pct() needs a sample taken ~30 min ago (+/- tol), else None (fail-closed)."""

    def __init__(self, keep_s: float = 5400):
        self.keep, self.h = keep_s, {}

    def add(self, key: str, price, now: float | None = None):
        if not price or price <= 0:
            return
        now = time.time() if now is None else now
        h = self.h.setdefault(key, [])
        h.append((now, price))
        self.h[key] = [(t, v) for t, v in h if now - t <= self.keep]

    def change_pct(self, key: str, price_now, window_s: float = 1800, tol_s: float = 300,
                   now: float | None = None):
        if not price_now or price_now <= 0:
            return None
        now = time.time() if now is None else now
        cands = [(abs((now - t) - window_s), v) for t, v in self.h.get(key, [])
                 if abs((now - t) - window_s) <= tol_s]
        if not cands:
            return None
        old = min(cands)[1]
        return round((price_now / old - 1) * 100, 2)

    def ready(self, key: str, window_s: float = 1800, tol_s: float = 300, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return any(abs((now - t) - window_s) <= tol_s for t, _ in self.h.get(key, []))


# --------------------------------------------------------------------------- persistence
def save_history(path: str, hist: "PriceHistory", vol: "VolumeTracker"):
    """Survives a restart, so the 30-minute warm-up is not lost. Never raises."""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"price": hist.h, "volume": vol.hist, "saved": time.time()}, f)
        os.replace(tmp, path)
    except Exception:
        pass


def load_history(path: str, hist: "PriceHistory", vol: "VolumeTracker", max_age_s: float = 5400):
    """Loads samples; the file is ignored if too old. Returns the number of tokens restored."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - d.get("saved", 0) > max_age_s:
            return 0
        now = time.time()
        hist.h = {k: [(float(t), float(v)) for t, v in rows if now - t <= hist.keep]
                  for k, rows in d.get("price", {}).items()}
        vol.hist = {k: [(float(t), float(v)) for t, v in rows if now - t <= vol.keep]
                    for k, rows in d.get("volume", {}).items()}
        return len(hist.h)
    except Exception:
        return 0
