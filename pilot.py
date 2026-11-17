#!/usr/bin/env python3
"""
FOMO.family Pilot v4  (provider: Claude by default, Grok optional)

The model OBSERVES the screen and PROPOSES. risk.py (plain Python) DECIDES:
entry filters, sizing, TP/stop/trailing, daily circuit breaker, max trades.

Modes
  (default)   PAPER: no click, no money. Decisions are simulated and logged.
  --navigate  PAPER + harmless navigation clicks allowed (never buy/sell/confirm).
  --live      REAL clicks. Entries need your y/n in the terminal (unless --auto-entry).

Keys (in .env, same folder)
  ANTHROPIC_API_KEY=...   for --provider anthropic (default)
  XAI_API_KEY=...         for --provider xai
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import sys
import time
from collections import Counter

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from notify import Notifier, msg_entry, msg_exit, msg_report
from reader import BtcChange
from risk import CONFIRM_WORDS, RiskManager, Rules, element_gate, ui_gate
from scanner import (Dex, PriceHistory, load_history, save_history, VolumeTracker, group_pairs, metrics_from_group,
                     parse_fomo_list, resolve_token)

load_dotenv()

for stream in (sys.stdout, sys.stderr):
    if (stream.encoding or "").lower().replace("-", "") != "utf8":
        stream.reconfigure(encoding="utf-8")


class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            super().emit(record)
        except UnicodeEncodeError:
            pass


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler("pilot.log", encoding="utf-8"), SafeStreamHandler(sys.stdout)],
)
logger = logging.getLogger("pilot")

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
MAX_API_ERRORS_IN_A_ROW = 5

SYSTEM_PROMPT = """You are the eyes of a trading desk on fomo.family. You receive a screenshot and a UI snapshot.
You do NOT decide sizes, stops or exits: the code enforces all risk rules. You only
(1) read numbers on screen, (2) say whether a token looks worth an entry, (3) say which UI step to do next.

Return ONLY one JSON object, no markdown:
{
  "intent": "enter" | "none" | "stop",
  "token": "symbol of the candidate token or null",
  "metrics": {
    "price": number, "volume_24h": number (USD), "market_cap": number (USD),
    "age_hours": number, "change_30m_pct": number, "change_1h_pct": number,
    "top5_holders_pct": number, "liquidity_usd": number, "btc_change_1h_pct": number
  },
  "open_positions": [ {"token": "symbol", "price": number, "volume_drop_1h_pct": number or null} ],
  "ui_action": {"action": "click" | "type" | "none", "selector": "visible text / placeholder / CSS", "value": ""},
  "reason": "short"
}
Rules for you:
- Plain numbers only (no "$", "M", "K"): convert 1.2M to 1200000.
- If a number is NOT clearly visible, put null. NEVER guess or estimate.
- open_positions = tokens you currently hold that are visible on screen.
- Never withdraw, never Face ID, never transfer. If unsure: intent "none", ui_action "none"."""


AUTO_PROMPT = """You are the navigator of a trading desk on the fomo app. You receive a screenshot and a UI snapshot.
Prices, volume, market cap, liquidity, age are checked elsewhere by code: do NOT report them.
The user message names a TARGET token (symbol, chain, contract address).
1. If the page on screen is NOT the TARGET token, give ONE navigation step (use the app's search box,
   type the symbol, click the result whose symbol and contract address match the TARGET).
   Never click Buy / Sell / Confirm / Swap / Withdraw / Transfer.
2. If the page IS the TARGET token, read the top-10 holders % and the top-5 holders % if shown, and list the
   red flags the page visibly shows (unverified token, unlocked liquidity, bundled / sniper / insider
   warnings, high dev holding, honeypot or rug warning...).
Return ONLY one JSON object, no markdown:
{"page_token": "symbol shown on the page or null", "page_address": "contract address if visible else null",
 "top10_holders_pct": number or null, "top5_holders_pct": number or null, "red_flags": [strings],
 "ui_action": {"action": "click" | "type" | "none", "selector": "visible text / placeholder", "value": ""},
 "reason": "short"}
Plain numbers only. If a number is not clearly visible use null. NEVER guess."""


# Describes the element about to be clicked: itself, the button/link around it, and the submit
# button of its form (clicking inside a Buy form must be seen as a trade action).
ELEMENT_DESC_JS = """
e => {
  const parts = [];
  const add = el => {
    if (!el) return;
    for (const a of ['aria-label', 'title', 'id', 'name', 'href', 'type', 'data-testid', 'class'])
      parts.push(el.getAttribute(a) || '');
    parts.push(el.innerText || '', el.value || '');
  };
  add(e);
  add(e.closest('button, a, [role="button"]'));
  const form = e.closest('form');
  if (form) add(form.querySelector('button[type="submit"], input[type="submit"]'));
  return parts.join(' ').replace(/\\s+/g, ' ').trim().slice(0, 2000);
}
"""


class FatalAPIError(Exception):
    """Bad key, no credit, no access: retrying every few seconds is pointless."""


# --------------------------------------------------------------------------- providers
class AnthropicVision:
    name = "anthropic"

    def __init__(self, model: str):
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            logger.error("ANTHROPIC_API_KEY missing (put it in .env, same folder as pilot.py)")
            sys.exit(1)
        try:
            import anthropic
        except ImportError:
            logger.error("Package missing: pip install anthropic")
            sys.exit(1)
        self.anthropic = anthropic
        self.client = anthropic.AsyncAnthropic(api_key=key, timeout=60)
        self.model = model

    async def ask(self, image_b64: str, ui_text: str, system: str | None = None) -> str:
        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=system or SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                        {"type": "text", "text": "UI Snapshot:\n" + ui_text},
                    ],
                }],
            )
        except self.anthropic.APIStatusError as e:
            body = getattr(e.response, "text", "") or str(e)
            logger.error("Anthropic API error %s: %s", e.status_code, body)
            low = body.lower()
            if e.status_code in (401, 403) or "credit balance" in low or "billing" in low:
                raise FatalAPIError(f"{e.status_code}: check your key and your credit on platform.claude.com")
            raise
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


class XaiVision:
    name = "xai"

    def __init__(self, model: str):
        key = os.getenv("XAI_API_KEY")
        if not key:
            logger.error("XAI_API_KEY missing (put it in .env, same folder as pilot.py)")
            sys.exit(1)
        if not model:
            logger.error("No xAI model set: use --model <id> (see --list-models)")
            sys.exit(1)
        try:
            from openai import APIStatusError, AsyncOpenAI
        except ImportError:
            logger.error("Package missing: pip install openai")
            sys.exit(1)
        self.APIStatusError = APIStatusError
        self.client = AsyncOpenAI(api_key=key, base_url="https://api.x.ai/v1", timeout=60)
        self.model = model

    async def ask(self, image_b64: str, ui_text: str, system: str | None = None) -> str:
        messages = [
            {"role": "system", "content": system or SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}", "detail": "high"}},
                {"type": "text", "text": "UI Snapshot:\n" + ui_text},
            ]},
        ]
        try:
            resp = await self.client.chat.completions.create(
                model=self.model, messages=messages, max_completion_tokens=1500)
        except self.APIStatusError as e:
            logger.error("xAI API error %s: %s", e.status_code, e.response.text)
            if e.status_code in (401, 403):
                raise FatalAPIError(f"{e.status_code}: check your xAI key and credit")
            raise
        return (resp.choices[0].message.content or "").strip()


def make_provider(name: str, model: str):
    if name == "text":
        from reader import TextVision
        return TextVision()
    if name == "anthropic":
        return AnthropicVision(model or os.getenv("PILOT_MODEL") or DEFAULT_ANTHROPIC_MODEL)
    return XaiVision(model or os.getenv("XAI_MODEL", ""))


async def list_xai_vision_models():
    import httpx
    key = os.getenv("XAI_API_KEY")
    if not key:
        logger.error("XAI_API_KEY missing")
        return []
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get("https://api.x.ai/v1/language-models", headers=headers)
        if r.status_code != 200:
            r = await http.get("https://api.x.ai/v1/models", headers=headers)
            logger.info("Models (modalities unknown): %s", r.text[:2000])
            return []
        models = r.json().get("models", [])
    vision = []
    for m in models:
        mods = m.get("input_modalities", [])
        logger.info("model=%s input=%s", m.get("id"), mods)
        if "image" in mods:
            vision.append(m["id"])
    return vision


# --------------------------------------------------------------------------- pilot
class FomoPilot:
    def __init__(self, args, provider=None):
        self.args = args
        self.live = args.live
        self.provider = provider or make_provider(args.provider, args.model)
        self.running = True
        self.page = None
        self.pending = None  # approved trade waiting to be executed in the UI (live only)
        self.api_errors = 0
        self.dex, self.btc, self.voltrack, self.hist = Dex(), BtcChange(), VolumeTracker(), PriceHistory()
        self.target, self.queue, self.last_scan, self.cooldown = None, [], 0.0, {}
        self.browser = None
        self.notifier = Notifier(getattr(args, 'ntfy_topic', None))
        self.last_report_day, self.halt_alerted = None, None
        self.history_file = os.path.join(os.path.dirname(os.path.abspath(args.state_file)) or ".", "history.json")
        n = load_history(self.history_file, self.hist, self.voltrack)
        if n:
            logger.info("Historique de prix rechargé (%d tokens) : pas besoin de refaire les 30 min d'attente.", n)
        rules = Rules()
        rules.max_positions = args.max_positions
        rules.min_change_1h = getattr(args, "min_1h", rules.min_change_1h)
        rules.min_change_30m = getattr(args, "min_30m", rules.min_change_30m)
        rules.use_30m = bool(getattr(args, "auto", False))   # auto mode builds the 30m change itself
        self.risk = RiskManager(rules, capital=args.capital, state_path=args.state_file)

    # ---------- screen ----------
    async def take_snapshot(self) -> dict:
        shot = await self.page.screenshot(full_page=False, type="jpeg", quality=70)
        ui = await self.page.evaluate(
            """
            () => {
                const els = [];
                document.querySelectorAll('button, a, input, [role="button"]').forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        els.push({
                            tag: el.tagName,
                            text: (el.innerText || el.placeholder || '').trim().slice(0, 80),
                            role: el.getAttribute('role') || '',
                            id: el.id || '',
                            class: (el.className && el.className.toString().slice(0, 60)) || ''
                        });
                    }
                });
                return { url: location.href, title: document.title,
                         visible_text: document.body.innerText.slice(0, 6000),
                         interactive: els.slice(0, 40) };
            }
            """
        )
        return {"screenshot": base64.b64encode(shot).decode("ascii"), "ui": ui}

    # ---------- model ----------
    @staticmethod
    def _extract_json(raw: str) -> dict:
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                raise ValueError("no JSON object found")
            return json.loads(m.group(0))

    async def ask_model(self, snap: dict) -> dict:
        ui_text = json.dumps(snap["ui"], ensure_ascii=False)
        try:
            raw = await self.provider.ask(snap["screenshot"], ui_text)
            self.api_errors = 0
        except FatalAPIError:
            raise
        except Exception as e:
            self.api_errors += 1
            logger.error("Model call failed (%d in a row): %s", self.api_errors, e)
            if self.api_errors >= MAX_API_ERRORS_IN_A_ROW:
                raise FatalAPIError(f"{self.api_errors} API errors in a row")
            return {"intent": "none"}
        logger.info("Model raw: %s", raw)
        try:
            return self._extract_json(raw)
        except Exception as e:
            logger.error("JSON parse error: %s", e)
            return {"intent": "none"}

    # ---------- UI ----------
    def _locator(self, selector: str):
        if re.match(r"^[#.\[]|[>\[\]=]", selector):
            return self.page.locator(selector).first
        return self.page.get_by_text(selector, exact=False).first

    async def exec_ui(self, ui: dict) -> bool:
        """Runs one UI step if the gate allows it. Returns True if a click/type happened."""
        if not isinstance(ui, dict):
            return False
        act = str(ui.get("action", "none")).lower()
        selector = str(ui.get("selector", "") or "")
        value = str(ui.get("value", "") or "")
        if act in ("none", ""):
            return False

        allowed, value, why = ui_gate(selector, value, act, self.pending)
        if not allowed:
            logger.warning("UI BLOCKED (%s): %s | %s | %s", why, act, selector, value)
            return False
        if not (self.live or self.args.navigate):
            logger.info("[PAPER] would do: %s | %s | %s", act, selector, value)
            return False
        try:
            if act == "click":
                target = self._locator(selector)
            elif act == "type":
                target = self.page.get_by_placeholder(selector, exact=False).first
                if await target.count() == 0:
                    target = self.page.get_by_label(selector, exact=False).first
                if await target.count() == 0:
                    target = self.page.locator("input:visible").first
            else:
                logger.warning("Unsupported UI action: %s", act)
                return False
            # 2nd gate: what the element REALLY is, whatever the selector says
            desc = await target.evaluate(ELEMENT_DESC_JS, timeout=5000)
            ok, why = element_gate(desc, act, self.pending)
            if not ok:
                logger.warning("UI BLOCKED (%s): %s | %s | element: %s", why, act, selector, str(desc)[:120])
                return False
            if act == "click":
                await target.click(timeout=5000)
            else:
                await target.fill(value, timeout=5000)
            logger.info("UI done: %s | %s | %s", act, selector, value)
            return True
        except Exception as e:
            logger.error("UI error: %s", e)
            return False

    # ---------- trades ----------
    async def handle_plan(self, plan: dict):
        for line in plan["log"]:
            logger.info(line)

        for ex in plan["exits"]:
            logger.info("EXIT approved: %s", ex)
            if not self.live:
                pnl = self.risk.apply_exit(ex["token"], ex["frac"], ex["price"], ex["reason"], mode="paper")
                logger.info("[PAPER] exit done, pnl $%.2f | %s", pnl, self.risk.status())
                t, m = msg_exit(ex, pnl)
                await self.notifier.send(t, m, priority=4 if pnl < 0 else 3, tags="chart_with_downwards_trend" if pnl < 0 else "moneybag")
            elif self.pending is None:
                self.pending = {"kind": "exit", "item": ex, "amount_str": str(ex["sell_pct_of_current"]),
                                "ttl": 8, "clicked_trade": False}
                break  # one trade at a time

        if plan["entry"] and not plan["exits"]:
            e = plan["entry"]
            logger.info("ENTRY approved: %s", e)
            if not self.live:
                self.risk.open_position(e["token"], e["price"], e["usd"], e["stop_pct"], mode="paper", ref=e.get("ref", ""))
                logger.info("[PAPER] entry recorded | %s", self.risk.status())
                t, m = msg_entry(e)
                await self.notifier.send(t, m, tags="rocket")
            elif self.pending is None:
                ok = self.args.auto_entry
                if not ok:
                    q = f"\n>>> Enter {e['token']} for ${e['usd']} (stop -{e['stop_pct']}%)? [y/N] "
                    ok = (await asyncio.to_thread(input, q)).strip().lower() == "y"
                if ok:
                    self.pending = {"kind": "entry", "item": e, "amount_str": f"{e['usd']:.2f}",
                                    "ttl": 8, "clicked_trade": False}
                else:
                    logger.info("Entry declined by you.")

    def complete_pending(self, ui: dict):
        """A confirm click ran while a trade was approved -> update the books."""
        p = self.pending
        if not p:
            return
        sel = str(ui.get("selector", ""))
        if re.search(r"buy|sell|acheter|vendre|confirm|valider|swap", sel, re.I):
            p["clicked_trade"] = True
        if CONFIRM_WORDS.search(sel):
            it = p["item"]
            if p["kind"] == "entry":
                self.risk.open_position(it["token"], it["price"], it["usd"], it["stop_pct"], mode="live")
            else:
                self.risk.apply_exit(it["token"], it["frac"], it["price"], it["reason"], mode="live")
            logger.info("LIVE trade recorded | %s", self.risk.status())
            self.pending = None

    def tick_pending(self):
        p = self.pending
        if not p:
            return
        p["ttl"] -= 1
        if p["ttl"] <= 0:
            if p["clicked_trade"]:
                logger.error("Trade clicks were made but never confirmed: books may be out of sync. "
                             "STOPPING. Check fomo manually, then delete state.json if needed.")
                self.running = False
            else:
                logger.warning("Approved trade expired without any trade click, dropped.")
            self.pending = None

    # ---------- auto mode: scan -> code filters -> page check -> paper entry ----------
    async def _read_list(self, page, path: str) -> str:
        """Loads a fomo list page and WAITS for the list to be rendered (a background tab can be slow)."""
        marker = "Position in this view"
        url = "https://fomo.family/" + path.strip().strip("/")
        text = ""
        for attempt in (1, 2):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_function(
                    f"document.body && document.body.innerText.includes('{marker}')",
                    timeout=15000, polling=500)
            except Exception as e:
                logger.info("SCAN: attente de la liste %s (essai %d) : %s", path, attempt, str(e)[:80])
            text = await page.evaluate("document.body ? document.body.innerText : ''")
            if marker in text:
                return text
            if attempt == 1:
                try:
                    await page.bring_to_front()      # background tabs get throttled by Chrome
                except Exception:
                    pass
        logger.warning("SCAN: page %s illisible (%d caractères, url=%s). Début : %r",
                       path, len(text), page.url, text[:160])
        return text

    async def scan_fomo(self) -> list[dict]:
        """Reads fomo's public lists, resolves each token on-chain, applies the code filters."""
        texts = []
        page = await self.page.context.new_page()
        try:
            for path in self.args.lists.split(","):
                texts.append(await self._read_list(page, path))
        finally:
            await page.close()

        seen, items = set(), []
        for t in texts:
            for it in parse_fomo_list(t):
                if it["symbol"] not in seen:
                    seen.add(it["symbol"])
                    items.append(it)

        btc = await self.btc.get()
        if btc is None:
            logger.warning("SCAN: BTC 1h illisible (Binance, Kraken et CoinGecko ont échoué), entrées refusées ce tour")
        stats, cands, err0, now, warm = Counter(), [], self.dex.errors, time.time(), 0
        for it in items:
            pairs = await self.dex.search(it["symbol"])
            g, why = resolve_token(it["symbol"], it["price"], pairs)
            if g is None:
                stats[why] += 1
                continue
            m = metrics_from_group(g, btc)
            key = f"{g['chain']}:{g['address']}"
            m["change_30m_pct"] = self.hist.change_pct(key, m["price"], now=now)   # from our own samples
            warm += self.hist.ready(key, now=now)
            self.hist.add(key, m["price"], now=now)                                 # sampled even during cooldown
            if self.cooldown.get(it["symbol"], 0) > now:
                stats["déjà vus"] += 1
                continue
            if self.risk.check_entry(it["symbol"], m, skip={"holders", "flags"}):
                stats["filtres desk"] += 1
                continue
            cands.append({"symbol": it["symbol"], "chain": g["chain"], "address": g["address"], "metrics": m})
        save_history(self.history_file, self.hist, self.voltrack)
        logger.info("SCAN: %d tokens lus | historique 30 min prêt : %d | écartés : %s | erreurs API : %d | candidats : %s",
                    len(items), warm, dict(stats) or "aucun", self.dex.errors - err0,
                    ", ".join(c["symbol"] for c in cands) or "aucun")
        return cands

    async def watch_positions(self):
        """Exits are computed from DexScreener prices (code), never from the model."""
        if not self.risk.positions:
            return
        ops = []
        for tok, pos in list(self.risk.positions.items()):
            if ":" not in (pos.ref or ""):
                logger.warning("WARNING %s: no on-chain reference, exits not evaluated", tok)
                continue
            chain, addr = pos.ref.split(":", 1)
            groups = [g for g in group_pairs(await self.dex.token_pairs(addr, chain))]
            if not groups:
                logger.warning("WARNING %s: price unavailable this cycle, exits not evaluated", tok)
                continue
            g = max(groups, key=lambda x: x["liq"])
            m = metrics_from_group(g, None)
            ops.append({"token": tok, "price": m["price"],
                        "volume_drop_1h_pct": self.voltrack.update(tok, m["volume_h1"])})
        await self.handle_plan(self.risk.process({"intent": "none", "open_positions": ops}))

    async def verify_target(self, snap: dict):
        """The model only navigates and reads holders + red flags. All numbers come from code."""
        tgt = self.target
        tgt["ttl"] -= 1
        ui_text = (f"TARGET: symbol={tgt['symbol']} chain={tgt['chain']} address={tgt['address']}\n"
                   "UI Snapshot:\n" + json.dumps(snap["ui"], ensure_ascii=False))
        try:
            raw = await self.provider.ask(snap["screenshot"], ui_text, system=AUTO_PROMPT)
            self.api_errors = 0
            logger.info("Nav raw: %s", raw)
            d = self._extract_json(raw)
        except FatalAPIError:
            raise
        except Exception as e:
            self.api_errors += 1
            logger.error("Verification call failed (%d in a row): %s", self.api_errors, e)
            if self.api_errors >= MAX_API_ERRORS_IN_A_ROW:
                raise FatalAPIError(f"{self.api_errors} API errors in a row")
            d = {}

        on_page = str(d.get("page_token") or "").upper() == tgt["symbol"].upper()
        addr_ok = d.get("page_address") in (None, "", tgt["address"])
        flags = d.get("red_flags")
        has_holders = d.get("top5_holders_pct") is not None or d.get("top10_holders_pct") is not None
        if on_page and addr_ok and isinstance(flags, list) and has_holders:
            pairs = await self.dex.token_pairs(tgt["address"], tgt["chain"])
            groups = group_pairs(pairs)
            if groups:  # fresh numbers right before the decision
                g = max(groups, key=lambda x: x["liq"])
                metrics = metrics_from_group(g, await self.btc.get())
                metrics["change_30m_pct"] = self.hist.change_pct(f"{tgt['chain']}:{tgt['address']}", metrics["price"])
                metrics.update(top5_holders_pct=d.get("top5_holders_pct"),
                               top10_holders_pct=d.get("top10_holders_pct"), red_flags=flags)
                logger.info("VERIF: %s page lue : top10=%s top5=%s alertes=%s", tgt["symbol"],
                            d.get("top10_holders_pct"), d.get("top5_holders_pct"), flags or "aucune")
                decision = {"intent": "enter", "token": tgt["symbol"], "metrics": metrics,
                            "ref": f"{tgt['chain']}:{tgt['address']}", "open_positions": []}
                self.cooldown[tgt["symbol"]] = time.time() + 900
                self.target = None
                await self.handle_plan(self.risk.process(decision))
                return
            logger.warning("VERIF: %s price data unavailable, abandoned", tgt["symbol"])
            self.cooldown[tgt["symbol"]] = time.time() + 300
            self.target = None
            return

        await self.exec_ui(d.get("ui_action") or {})
        if tgt["ttl"] <= 0:
            logger.info("VERIF: abandon %s (page non trouvée après %d essais)", tgt["symbol"], self.args.verify_cycles)
            self.cooldown[tgt["symbol"]] = time.time() + 300
            self.target = None

    async def alerts(self):
        """Circuit breaker (once per day) and daily report (once, after --report-hour local time)."""
        today = time.strftime("%Y-%m-%d")
        if self.risk.halted and self.halt_alerted != today:
            self.halt_alerted = today
            await self.notifier.send("STOP du jour", "Coupe-circuit déclenché : plus aucune entrée aujourd'hui. "
                                     + self.risk.status(), priority=5, tags="octagonal_sign")
        if time.localtime().tm_hour >= self.args.report_hour and self.last_report_day != today:
            self.last_report_day = today
            r = self.risk
            t, m = msg_report(r.capital, r.day_start_capital, r.trades_today, list(r.positions), r.halted)
            await self.notifier.send(t, m, priority=2, tags="bar_chart")

    async def auto_cycle(self):
        await self.alerts()
        await self.watch_positions()
        if self.risk.halted:
            logger.warning("Daily circuit breaker ACTIVE: no new entries until tomorrow.")
            return
        now = time.time()
        if now - self.last_scan >= self.args.scan_every or (
                self.target is None and not self.queue and now - self.last_scan >= 30):
            self.queue, self.last_scan = await self.scan_fomo(), now
        if self.target is None and self.queue:
            self.target = self.queue.pop(0)
            self.target["ttl"] = self.args.verify_cycles
            logger.info("VERIF: début %s (%s)", self.target["symbol"], self.target["chain"])
        if self.target:
            await self.verify_target(await self.take_snapshot())

    # ---------- browser lost ----------
    def _browser_dead(self) -> bool:
        try:
            return (self.browser is not None and not self.browser.is_connected()) or \
                   (self.page is not None and self.page.is_closed())
        except Exception:
            return True

    async def _recover(self, p) -> bool:
        """Chrome was closed: keep watching open positions through DexScreener (no browser needed)
        and retry the connection every 30 s. Gives up after --reconnect-min minutes."""
        logger.error("ATTENTION: Chrome fermé / déconnecté. Je surveille les positions et je réessaie toutes les 30 s.")
        await self.notifier.send("Chrome ferme", "Chrome est fermé ou déconnecté. Je surveille les positions et je "
                                 "réessaie toutes les 30 s. Rouvre Chrome en mode debug.", priority=4, tags="warning")
        deadline = time.time() + self.args.reconnect_min * 60
        while time.time() < deadline and self.running:
            try:
                if self.args.auto:
                    await self.watch_positions()
                browser = await p.chromium.connect_over_cdp("http://localhost:9222")
                ctx = browser.contexts[0]
                self.browser = browser
                self.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await self.page.goto("https://fomo.family", wait_until="domcontentloaded")
                logger.info("Chrome reconnecté, reprise.")
                self.target = None
                return True
            except Exception as e:
                logger.info("Chrome toujours indisponible (%s)", str(e)[:60])
            await asyncio.sleep(30)
        return False

    # ---------- main loop ----------
    async def run(self):
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp("http://localhost:9222")
                self.browser = browser
                ctx = browser.contexts[0]
                self.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                logger.info("Connected to existing Chrome (CDP).")
            except Exception:
                logger.info("No Chrome in debug mode - launching a new one")
                browser = await p.chromium.launch(headless=False, channel="chrome")
                self.browser = browser
                self.page = await (await browser.new_context()).new_page()

            await self.page.goto("https://fomo.family", wait_until="domcontentloaded")
            await self.notifier.send("Bot demarre", "Bot lancé en mode " + ("LIVE" if self.live else "PAPER")
                                     + ". " + self.risk.status(), priority=2, tags="white_check_mark")
            logger.info("Opened fomo.family. Log in manually if needed. Mode=%s provider=%s model=%s | %s",
                        "LIVE" if self.live else "PAPER", self.provider.name, self.provider.model,
                        self.risk.status())

            cycles = 0
            while self.running:
                if self.args.max_cycles and cycles >= self.args.max_cycles:
                    break
                cycles += 1
                try:
                    if self.args.auto:
                        await self.auto_cycle()
                        await asyncio.sleep(self.args.interval)
                        continue
                    snap = await self.take_snapshot()
                    if self.args.dump:
                        with open("page_dump.txt", "w", encoding="utf-8") as f:
                            f.write("URL: %s\nTITLE: %s\n\n%s" % (
                                snap["ui"].get("url"), snap["ui"].get("title"), snap["ui"].get("visible_text")))
                    decision = await self.ask_model(snap)
                    if self.provider.name == "text":
                        logger.info("Read: token=%s metrics=%s", decision.get("token"), decision.get("metrics"))
                    if decision.get("intent") == "stop":
                        logger.info("Model asked to stop. Stopping.")
                        break

                    if self.pending is None:
                        await self.handle_plan(self.risk.process(decision))

                    ui = decision.get("ui_action") or {}
                    if await self.exec_ui(ui):
                        self.complete_pending(ui)
                    self.tick_pending()

                    if self.risk.halted:
                        logger.warning("Daily circuit breaker ACTIVE: no new entries until tomorrow.")
                    await asyncio.sleep(self.args.interval)
                except FatalAPIError as e:
                    logger.error("STOPPING: %s", e)
                    await self.notifier.send("BOT ARRETE", f"Arrêt : {e}", priority=5, tags="rotating_light")
                    break
                except Exception as e:
                    logger.error("Cycle error: %s", e)
                    if self._browser_dead():
                        if not await self._recover(p):
                            logger.error("STOPPING: Chrome est fermé depuis trop longtemps. Relance Chrome en "
                                         "mode debug puis le bot.")
                            await self.notifier.send("BOT ARRETE", "Chrome fermé trop longtemps, le bot s'est arrêté.",
                                                     priority=5, tags="rotating_light")
                            break
                        continue
                    await asyncio.sleep(5)
            logger.info("Pilot stopped. %s", self.risk.status())
            if self.risk.positions:
                await self.notifier.send("Positions ouvertes", "Le bot est arrêté mais ces positions restent ouvertes : "
                                         + ", ".join(self.risk.positions), priority=5, tags="warning")
            if self.risk.positions:
                logger.warning("Positions still open in the books: %s. The bot is no longer watching "
                               "them, check fomo.family yourself.", ", ".join(self.risk.positions))


def parse_args():
    ap = argparse.ArgumentParser(description="FOMO Pilot v4")
    ap.add_argument("--provider", choices=["text", "anthropic", "xai"], default="text",
                    help="text = free, reads the page text with code (default)")
    ap.add_argument("--model", default="", help=f"default for anthropic: {DEFAULT_ANTHROPIC_MODEL}")
    ap.add_argument("--list-models", action="store_true", help="xai only: list models with image input")
    ap.add_argument("--ntfy-topic", default=None, help="canal ntfy (sinon NTFY_TOPIC du .env)")
    ap.add_argument("--report-hour", type=int, default=21, help="heure locale du rapport quotidien")
    ap.add_argument("--reconnect-min", type=float, default=30,
                    help="minutes to keep retrying if Chrome is closed before stopping")
    ap.add_argument("--capital", type=float, default=20, help="Capital in $ (used for risk sizing)")
    ap.add_argument("--max-positions", type=int, default=5)
    ap.add_argument("--navigate", action="store_true", help="paper mode but allow harmless navigation clicks")
    ap.add_argument("--live", action="store_true", help="REAL trades (default is paper)")
    ap.add_argument("--auto-entry", action="store_true", help="live: skip the y/n confirmation on entries")
    ap.add_argument("--auto", action="store_true", help="AUTO (paper only): scans fomo lists, filters with code, checks the page, simulates entries")
    ap.add_argument("--lists", default="top-movers", help="fomo public pages to scan, comma separated (default: top-movers)")
    ap.add_argument("--scan-every", type=float, default=60, help="seconds between scans (auto)")
    ap.add_argument("--min-1h", type=float, default=50.0, help="momentum: min %% change on 1h (desk rule: 50)")
    ap.add_argument("--min-30m", type=float, default=20.0, help="momentum: min %% change on 30m (desk rule: 20)")
    ap.add_argument("--verify-cycles", type=int, default=6, help="max cycles to open + read one token page (auto)")
    ap.add_argument("--dump", action="store_true", help="save the page text to page_dump.txt each cycle (to calibrate reader.py)")
    ap.add_argument("--interval", type=float, default=30, help="seconds between cycles (each cycle = 1 paid API call)")
    ap.add_argument("--max-cycles", type=int, default=0, help="0 = unlimited")
    ap.add_argument("--state-file", default="state.json")
    ap.add_argument("--reset-state", action="store_true", help="delete state.json (new capital / positions)")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.list_models:
        if args.provider != "xai":
            print(f"Anthropic: default model is {DEFAULT_ANTHROPIC_MODEL} (it reads images). "
                  "Nothing to list. Use --provider xai --list-models for Grok.")
        else:
            v = asyncio.run(list_xai_vision_models())
            print("\nxAI models with image input:", v or "(see log above)")
        sys.exit(0)
    if args.reset_state and os.path.exists(args.state_file):
        os.remove(args.state_file)
    if args.auto:
        if args.live:
            print("--auto n'est pas autorisé avec --live pour l'instant (paper seulement).")
            sys.exit(1)
        if args.provider == "text":
            args.provider = "anthropic"
            print("--auto utilise un modèle pour naviguer : provider = anthropic")
        if not args.navigate:
            print("ATTENTION : sans --navigate le bot scanne mais ne peut pas ouvrir les pages "
                  "pour lire les holders. Ajoute --navigate.")
    try:
        asyncio.run(FomoPilot(args).run())
    except KeyboardInterrupt:
        logger.info("Manual stop (Ctrl+C)")
