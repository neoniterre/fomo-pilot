"""
reader.py: reads trading metrics from the page TEXT with plain code. No LLM, no API cost.

Fail-closed: a metric that is not found stays None, and risk.py refuses the entry.
The label patterns below are guesses. Run `python pilot.py --dump` on a token page,
open page_dump.txt, and adjust LABELS if a number is missed or wrong.
"""
from __future__ import annotations

import json
import re
import time

NUM = r"([-+]?[^\S\n]*[$€]?[^\S\n]*\d[\d.,]*(?:[KMBkmb](?![A-Za-z]))?)[^\S\n]*%?"

# metric -> label regexes (first match wins). Value must follow the label, same line or next.
LABELS = {
    "price": [r"price"],
    "volume_24h": [r"24\s*h\s*vol(?:ume)?", r"vol(?:ume)?\s*24\s*h", r"volume"],
    "market_cap": [r"market\s*cap", r"m\.?\s*cap"],
    "liquidity_usd": [r"liquidity", r"\bliq\b"],
    "top5_holders_pct": [r"top\s*5\s*holders?", r"top\s*5"],
    "change_30m_pct": [r"(?<![\d.])30\s*m(?:in)?"],
    "change_1h_pct": [r"(?<![\d.])1\s*h(?:our)?(?!\w)"],
}
AGE_LABELS = [r"token\s*age", r"\bage\b", r"created", r"launched"]


def parse_number(s: str | None):
    """'$1.2M' -> 1200000.0 ; '12,5K' -> 12500.0 ; '-8.4' -> -8.4 ; garbage -> None"""
    if s is None:
        return None
    s = s.strip().replace(" ", "").replace("$", "").replace("€", "")
    mult = 1.0
    if s and s[-1] in "KkMmBb":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1].lower()]
        s = s[:-1]
    if "," in s and "." in s:
        s = s.replace(",", "")                       # 1,234.5
    elif "," in s:
        left, _, right = s.rpartition(",")
        s = (left.replace(",", "") + "." + right) if len(right) <= 2 else s.replace(",", "")
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_age_hours(s: str | None):
    """'2h 15m' -> 2.25 ; '3d' -> 72 ; '45m' -> 0.75 ; '1d 4h' -> 28"""
    if not s:
        return None
    total, found = 0.0, False
    for val, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(d|h|m|min)\b", s.lower()):
        v = float(val.replace(",", "."))
        total += v * {"d": 24, "h": 1, "m": 1 / 60, "min": 1 / 60}[unit]
        found = True
    return round(total, 4) if found else None


def _after_label(text: str, labels: list[str], value_re: str):
    for lab in labels:
        m = re.search(lab + r"[^\S\n]*[:\-]?\s{0,3}" + value_re, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def extract_metrics(text: str) -> dict:
    out = {}
    for key, labs in LABELS.items():
        out[key] = parse_number(_after_label(text, labs, NUM))
    out["age_hours"] = parse_age_hours(
        _after_label(text, AGE_LABELS, r"((?:\d+[^\S\n]*(?:d|h|min|m)\b[^\S\n]*){1,3})"))
    return out


def extract_token(title: str, url: str, text: str) -> str | None:
    m = re.search(r"\$([A-Za-z0-9]{2,12})\b", title or "") or re.search(r"\$([A-Za-z0-9]{2,12})\b", text[:600])
    if m:
        return m.group(1).upper()
    tail = (url or "").rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    return tail[:20] or None


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v > 0 else None


def parse_binance_klines(rows):
    """1-minute klines [[openTime, open, high, low, close, ...], ...] -> % change over ~1h (needs >= 60 rows)."""
    try:
        if len(rows) < 60:
            return None
        old, new = _f(rows[0][1]), _f(rows[-1][4])
        return round((new / old - 1) * 100, 3) if old and new else None
    except Exception:
        return None


def parse_kraken_ohlc(data):
    """Kraken OHLC (1m) -> % change over ~1h (needs >= 60 candles)."""
    try:
        res = data.get("result") or {}
        rows = next(v for k, v in res.items() if k != "last" and isinstance(v, list))
        if len(rows) < 61:
            return None
        old, new = _f(rows[-61][1]), _f(rows[-1][4])
        return round((new / old - 1) * 100, 3) if old and new else None
    except Exception:
        return None


class BtcChange:
    """BTC 1h % change, 3 free public sources tried in order (Binance, Kraken, CoinGecko), cached.
    A last good value up to `stale_s` old is reused if all sources fail; beyond that None -> entries refused."""

    def __init__(self, ttl: float = 120, stale_s: float = 600):
        self.ttl, self.stale_s = ttl, stale_s
        self.t, self.v = 0.0, None
        self.good_t, self.good_v, self.source = 0.0, None, None

    async def _fetch(self):
        import httpx
        async with httpx.AsyncClient(timeout=10) as h:
            for name, call in (("binance", self._binance), ("kraken", self._kraken), ("coingecko", self._gecko)):
                try:
                    v = await call(h)
                except Exception:
                    v = None
                if v is not None:
                    return name, v
        return None, None

    @staticmethod
    async def _binance(h):
        r = await h.get("https://api.binance.com/api/v3/klines",
                        params={"symbol": "BTCUSDT", "interval": "1m", "limit": 61})
        return parse_binance_klines(r.json())

    @staticmethod
    async def _kraken(h):
        r = await h.get("https://api.kraken.com/0/public/OHLC", params={"pair": "XBTUSD", "interval": 1})
        return parse_kraken_ohlc(r.json())

    @staticmethod
    async def _gecko(h):
        r = await h.get("https://api.coingecko.com/api/v3/coins/markets",
                        params={"vs_currency": "usd", "ids": "bitcoin", "price_change_percentage": "1h"})
        return float(r.json()[0]["price_change_percentage_1h_in_currency"])

    async def get(self):
        now = time.time()
        if now - self.t < self.ttl:
            return self.v
        self.t = now
        name, v = await self._fetch()
        if v is not None:
            self.good_t, self.good_v, self.source, self.v = now, v, name, v
        elif self.good_v is not None and now - self.good_t <= self.stale_s:
            self.v = self.good_v
        else:
            self.v = None
        return self.v


class TextVision:
    """Same interface as the LLM providers (ask(image_b64, ui_text) -> JSON string), zero cost."""
    name = "text"
    model = "text-parser"

    def __init__(self):
        self.btc = BtcChange()

    async def ask(self, image_b64: str, ui_text: str) -> str:
        ui = json.loads(ui_text.split("UI Snapshot:\n", 1)[-1])
        text = ui.get("visible_text", "") or ""
        token = extract_token(ui.get("title", ""), ui.get("url", ""), text)
        m = extract_metrics(text)
        m["btc_change_1h_pct"] = await self.btc.get()
        decision = {
            "intent": "enter" if token and m.get("price") else "none",
            "token": token,
            "metrics": m,
            # lets risk.py evaluate exits when the open position's page is on screen
            "open_positions": [{"token": token, "price": m["price"], "volume_drop_1h_pct": None}]
            if token and m.get("price") else [],
            "ui_action": {"action": "none"},
            "reason": "text parser",
        }
        return json.dumps(decision)
