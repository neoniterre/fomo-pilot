"""
Desk rules v4, enforced in code. No LLM involved here.

Grok only OBSERVES (reads numbers on screen) and PROPOSES.
This module decides: entry filters, position sizing, exits, daily limits.
Fail-closed: a missing / unreadable number = entry refused.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class Rules:
    # 1. Entry filter
    min_volume_24h: float = 150_000
    min_mcap: float = 1_000_000
    max_mcap: float = 80_000_000
    min_age_h: float = 1.0
    min_change_30m: float = 20.0
    min_change_1h: float = 50.0
    use_30m: bool = False     # False = momentum is "+50% 1h" only (30m not available from the data source)
    max_top5_holders: float = 40.0
    min_liq_mcap_pct: float = 8.0
    max_pos_liq_pct: float = 1.5
    # 2. Sizing & risk
    risk_per_trade_pct: float = 0.8
    max_positions: int = 5
    max_exposure_pct: float = 25.0
    stop_min: float = 12.0
    stop_max: float = 15.0
    min_trade_usd: float = 1.0
    # 3. Exit
    tp1_pct: float = 40.0
    tp1_sell: float = 0.40   # fraction of the INITIAL position
    tp2_pct: float = 80.0
    tp2_sell: float = 0.30   # fraction of the INITIAL position
    trail_pct: float = 12.0  # active after TP1
    vol_drop_exit_pct: float = 60.0
    # 4. Strict rules
    max_trades_day: int = 15
    btc_block_pct: float = -5.0       # no entry if BTC 1h change <= this
    daily_loss_limit_pct: float = 3.0


def required_keys(rules):
    keys = ["price", "volume_24h", "market_cap", "age_hours", "change_1h_pct",
            "liquidity_usd", "btc_change_1h_pct"]
    if rules.use_30m:
        keys.append("change_30m_pct")
    return keys

# Never click / type these, whatever Grok says
FORBIDDEN = re.compile(
    r"withdraw|retrait|retirer|face\s*id|transfer|transf[eé]rer|send to|envoyer|"
    r"export|seed|private key|cl[eé] priv|passcode|password|mot de passe|"
    r"delete account|supprimer le compte",
    re.IGNORECASE,
)
# Anything that can move money: only allowed while an approved trade is pending
TRADE_WORDS = re.compile(
    r"\bbuy\b|\bsell\b|acheter|vendre|confirm|valider|\bswap\b|\btrade\b|\bmax\b|all.?in|100\s*%",
    re.IGNORECASE,
)
CONFIRM_WORDS = re.compile(r"confirm|valider|\bswap\b", re.IGNORECASE)
NUMERIC = re.compile(r"^[\d.,]+\s*%?$")


def _f(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # drop NaN


@dataclass
class Position:
    token: str
    entry_price: float
    initial_usd: float
    stop_pct: float
    high: float
    remaining_frac: float = 1.0
    tp1_done: bool = False
    tp2_done: bool = False
    opened_at: str = ""
    ref: str = ""   # "chain:address", used to follow the price with code

    def cost_remaining(self) -> float:
        return self.initial_usd * self.remaining_frac


def ui_gate(selector: str, value: str, act: str, pending: dict | None):
    """Decide if a UI action Grok asked for may run. Returns (allowed, value, why)."""
    selector, value = selector or "", value or ""
    if FORBIDDEN.search(f"{selector} {value}"):
        return False, value, "forbidden word"
    if act == "type" and NUMERIC.match(value.strip()):
        if not pending:
            return False, value, "amount typed without an approved trade"
        return True, pending["amount_str"], "amount overridden by risk manager"
    if TRADE_WORDS.search(selector) and not pending:
        return False, value, "trade-type click without an approved trade"
    return True, value, "ok"


class RiskManager:
    def __init__(self, rules: Rules, capital: float, state_path="state.json",
                 trade_log="trades.jsonl", today_fn=None):
        self.r = rules
        self.state_path = state_path
        self.trade_log = trade_log
        self.today_fn = today_fn or (lambda: datetime.now().strftime("%Y-%m-%d"))
        self.capital = float(capital)
        self.positions: dict[str, Position] = {}
        self.day = None
        self.day_start_capital = self.capital
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.halted = False
        self._load()
        self._roll_day()

    # ---------- persistence (so a restart does NOT reset the daily breaker) ----------
    def _load(self):
        if not (self.state_path and os.path.exists(self.state_path)):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                s = json.load(f)
            self.capital = s["capital"]
            self.day = s["day"]
            self.day_start_capital = s["day_start_capital"]
            self.daily_pnl = s["daily_pnl"]
            self.trades_today = s["trades_today"]
            self.halted = s["halted"]
            self.positions = {k: Position(**v) for k, v in s["positions"].items()}
        except Exception:
            pass  # corrupt state -> start clean (capital from args)

    def _save(self):
        if not self.state_path:
            return
        s = {
            "capital": self.capital, "day": self.day,
            "day_start_capital": self.day_start_capital,
            "daily_pnl": self.daily_pnl, "trades_today": self.trades_today,
            "halted": self.halted,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
        }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, self.state_path)

    def _log_trade(self, rec: dict):
        if not self.trade_log:
            return
        rec["ts"] = datetime.now(timezone.utc).isoformat()
        with open(self.trade_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _roll_day(self):
        today = self.today_fn()
        if self.day != today:
            self.day = today
            self.day_start_capital = self.capital
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.halted = False
            self._save()

    # ---------- helpers ----------
    @property
    def exposure(self) -> float:
        return sum(p.cost_remaining() for p in self.positions.values())

    def status(self) -> str:
        return (f"capital=${self.capital:.2f} exposure=${self.exposure:.2f} "
                f"positions={len(self.positions)} daily_pnl=${self.daily_pnl:+.2f} "
                f"trades_today={self.trades_today} halted={self.halted}")

    # ---------- entry ----------
    def check_entry(self, token: str, m: dict, skip=()) -> list[str]:
        self._roll_day()
        r, fails = self.r, []
        if self.halted:
            fails.append("circuit breaker active (daily loss limit hit)")
        if self.trades_today >= r.max_trades_day:
            fails.append(f"max trades/day reached ({r.max_trades_day})")
        if token in self.positions:
            fails.append("position already open on this token")
        if len(self.positions) >= r.max_positions:
            fails.append(f"max positions reached ({r.max_positions})")

        v = {k: _f(m.get(k)) for k in required_keys(r)}
        missing = [k for k, x in v.items() if x is None]
        # holders: top5 if known, else top10 as a SAFE proxy (top5 <= top10, so top10 < 40% => top5 < 40%)
        holders = _f(m.get("top5_holders_pct"))
        if holders is None:
            holders = _f(m.get("top10_holders_pct"))
        if "holders" not in skip and holders is None:
            missing.append("top5_holders_pct")
        if missing:
            fails.append("missing/unreadable metrics: " + ", ".join(missing))
            return fails

        if v["price"] <= 0:
            fails.append("invalid price")
        if v["btc_change_1h_pct"] <= r.btc_block_pct:
            fails.append(f"BTC {v['btc_change_1h_pct']}% in 1h (<= {r.btc_block_pct}%)")
        if not v["volume_24h"] > r.min_volume_24h:
            fails.append(f"volume 24h {v['volume_24h']:.0f} <= {r.min_volume_24h:.0f}")
        if not (r.min_mcap <= v["market_cap"] <= r.max_mcap):
            fails.append(f"market cap {v['market_cap']:.0f} outside [{r.min_mcap:.0f}, {r.max_mcap:.0f}]")
        if not v["age_hours"] > r.min_age_h:
            fails.append(f"token age {v['age_hours']}h <= {r.min_age_h}h")
        mom_ok = v["change_1h_pct"] >= r.min_change_1h
        if r.use_30m:
            mom_ok = mom_ok or v["change_30m_pct"] >= r.min_change_30m
        if not mom_ok:
            fails.append("momentum too weak (needs +50% 1h" + (" OR +20% 30m)" if r.use_30m else ")"))
        if holders is not None and not holders < r.max_top5_holders:
            fails.append(f"top5 holders {holders}% >= {r.max_top5_holders}%")
        flags = m.get("red_flags")
        if "flags" not in skip and isinstance(flags, list) and flags:
            fails.append("red flags on page: " + ", ".join(str(x) for x in flags[:3]))
        if v["market_cap"] > 0 and v["liquidity_usd"] / v["market_cap"] * 100 < r.min_liq_mcap_pct:
            fails.append("liquidity/market cap < 8%")
        return fails

    def size_position(self, m: dict, stop_pct: float | None = None):
        """size = risk / stop distance, then capped by exposure and pool liquidity."""
        r = self.r
        stop = min(max(stop_pct or r.stop_min, r.stop_min), r.stop_max)
        risk_usd = self.capital * r.risk_per_trade_pct / 100
        size = risk_usd / (stop / 100)
        notes = [f"risk ${risk_usd:.2f} / stop {stop}% = ${size:.2f}"]

        room = self.capital * r.max_exposure_pct / 100 - self.exposure
        if size > room:
            size = room
            notes.append(f"capped by 25% exposure (room ${max(room, 0):.2f})")
        liq = _f(m.get("liquidity_usd")) or 0.0
        liq_cap = liq * r.max_pos_liq_pct / 100
        if size > liq_cap:
            size = liq_cap
            notes.append(f"capped by 1.5% of pool (${liq_cap:.2f})")
        size = round(max(size, 0.0), 2)
        if size < r.min_trade_usd:
            notes.append(f"size ${size:.2f} below minimum ${r.min_trade_usd:.2f}")
            size = 0.0
        return size, stop, notes

    def open_position(self, token, price, usd, stop_pct, fill_price=None, mode="paper", ref=""):
        self._roll_day()
        entry = fill_price or price
        self.positions[token] = Position(
            token=token, entry_price=entry, initial_usd=usd, stop_pct=stop_pct,
            high=entry, opened_at=datetime.now(timezone.utc).isoformat(), ref=ref,
        )
        self.trades_today += 1
        slip = (entry / price - 1) * 100 if price else 0.0
        self._log_trade({"mode": mode, "side": "buy", "token": token, "usd": usd,
                         "theoretical_price": price, "fill_price": fill_price,
                         "slippage_pct": round(slip, 3), "stop_pct": stop_pct})
        self._save()

    # ---------- exits ----------
    def evaluate_exits(self, token, price, volume_drop_1h_pct=None):
        """Returns [(fraction_of_initial, reason)]. Code decides, not the LLM."""
        p, r = self.positions.get(token), self.r
        if p is None or price <= 0:
            return []
        p.high = max(p.high, price)
        self._save()
        chg = round((price / p.entry_price - 1) * 100, 6)  # avoid float edge (39.9999 vs 40)
        remaining = p.remaining_frac

        if chg <= -p.stop_pct:
            return [(remaining, f"stop-loss ({chg:.1f}%)")]
        if volume_drop_1h_pct is not None and volume_drop_1h_pct > r.vol_drop_exit_pct:
            return [(remaining, f"volume drop {volume_drop_1h_pct:.0f}% in 1h")]

        exits, tp1_active = [], p.tp1_done
        if not p.tp1_done and chg >= r.tp1_pct:
            f = min(r.tp1_sell, remaining)
            exits.append((f, f"TP1 (+{chg:.0f}%)"))
            remaining -= f
            tp1_active = True
        if not p.tp2_done and chg >= r.tp2_pct and remaining > 1e-9:
            f = min(r.tp2_sell, remaining)
            exits.append((f, f"TP2 (+{chg:.0f}%)"))
            remaining -= f
        if tp1_active and remaining > 1e-9 and price <= p.high * (1 - r.trail_pct / 100):
            exits.append((remaining, f"trailing stop (-{r.trail_pct:.0f}% from high)"))
        return exits

    def apply_exit(self, token, frac, price, reason, fill_price=None, mode="paper"):
        p = self.positions.get(token)
        if p is None:
            return 0.0
        self._roll_day()
        fill = fill_price or price
        frac = min(frac, p.remaining_frac)
        realized = frac * p.initial_usd * (fill / p.entry_price - 1)
        self.capital += realized
        self.daily_pnl += realized
        p.remaining_frac = round(p.remaining_frac - frac, 9)
        if reason.startswith("TP1"):
            p.tp1_done = True
        if reason.startswith("TP2"):
            p.tp2_done = True
        slip = (fill / price - 1) * 100 if price else 0.0
        self._log_trade({"mode": mode, "side": "sell", "token": token, "frac": round(frac, 4),
                         "theoretical_price": price, "fill_price": fill_price,
                         "slippage_pct": round(slip, 3), "pnl_usd": round(realized, 4),
                         "reason": reason})
        if p.remaining_frac <= 1e-6:
            del self.positions[token]
        if self.daily_pnl <= -self.r.daily_loss_limit_pct / 100 * self.day_start_capital:
            self.halted = True
        self._save()
        return realized

    # ---------- main entry point ----------
    def process(self, decision: dict) -> dict:
        """Takes Grok's observation/proposal, returns what the code APPROVES."""
        self._roll_day()
        out = {"exits": [], "entry": None, "log": []}

        seen = set()
        for o in decision.get("open_positions") or []:
            t, price = o.get("token"), _f(o.get("price"))
            if t not in self.positions:
                continue
            seen.add(t)
            if price is None or price <= 0:
                out["log"].append(f"{t}: unreadable price, exits NOT evaluated this cycle")
                continue
            cur = self.positions[t].remaining_frac
            for frac, reason in self.evaluate_exits(t, price, _f(o.get("volume_drop_1h_pct"))):
                out["exits"].append({
                    "token": t, "frac": frac, "price": price, "reason": reason,
                    "sell_pct_of_current": round(min(frac / cur, 1.0) * 100, 1),
                })
        for t in self.positions:
            if t not in seen:
                out["log"].append(f"WARNING {t}: open position not visible on screen, exits not evaluated")

        if out["exits"]:
            return out  # exits always come first; no new entry this cycle

        if decision.get("intent") != "enter":
            return out
        token, m = decision.get("token"), decision.get("metrics") or {}
        if not token:
            out["log"].append("ENTRY REFUSED: no token name")
            return out
        fails = self.check_entry(token, m)
        if fails:
            out["log"].append(f"ENTRY REFUSED {token}: " + "; ".join(fails))
            return out
        size, stop, notes = self.size_position(m)
        if size <= 0:
            out["log"].append(f"ENTRY REFUSED {token}: " + "; ".join(notes))
            return out
        out["entry"] = {"token": token, "price": _f(m["price"]), "usd": size,
                        "stop_pct": stop, "notes": notes, "ref": decision.get("ref", "")}
        return out
