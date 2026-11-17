#!/usr/bin/env python3
"""
summary.py : version simplifiée de pilot.log, en français.

  python summary.py              -> état + 20 derniers événements
  python summary.py --last 50    -> plus d'historique
  python summary.py --watch      -> se rafraîchit toutes les 10 s (Ctrl+C pour quitter)
  python summary.py --cloud      -> bot cloud : état + derniers trades lus sur GitHub (branche data, sans clé)
"""
import argparse
import json
import os
import re
import sys
import time

if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
    sys.stdout.reconfigure(encoding="utf-8")

LINE = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d+ \| (\w+) \| (.*)$")
FIELDS = ["price", "volume_24h", "market_cap", "age_hours", "change_30m_pct",
          "change_1h_pct", "top5_holders_pct", "liquidity_usd", "btc_change_1h_pct"]
NAMES = {"price": "prix", "volume_24h": "volume", "market_cap": "market cap",
         "age_hours": "âge", "change_30m_pct": "+30min", "change_1h_pct": "+1h",
         "top5_holders_pct": "top5 holders", "liquidity_usd": "liquidité",
         "btc_change_1h_pct": "BTC 1h"}


def read_records(path):
    """Groups log lines into records (a record can span several lines)."""
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.rstrip("\n")
            m = LINE.match(raw)
            if m:
                recs.append({"day": m.group(1), "t": m.group(2), "lvl": m.group(3), "msg": m.group(4)})
            elif recs:
                recs[-1]["msg"] += "\n" + raw
    return recs


def short(txt, n=110):
    txt = " ".join(txt.split())
    return txt if len(txt) <= n else txt[: n - 1] + "…"


REASONS = [
    ("missing/unreadable metrics:", "chiffres manquants :"),
    ("circuit breaker active (daily loss limit hit)", "coupe-circuit actif (perte max du jour)"),
    ("max trades/day reached", "max de trades du jour atteint"),
    ("position already open on this token", "position déjà ouverte sur ce token"),
    ("max positions reached", "max de positions atteint"),
    ("momentum too weak (needs +20% 30m OR +50% 1h)", "momentum trop faible (il faut +20% 30min OU +50% 1h)"),
    ("liquidity/market cap < 8%", "liquidité / market cap < 8%"),
    ("token age", "âge du token trop faible"),
    ("top5 holders", "top 5 holders trop concentrés"),
    ("market cap", "market cap hors limites"),
    ("volume 24h", "volume 24h trop faible"),
    ("invalid price", "prix invalide"),
    ("below minimum", "taille sous le minimum"),
    ("no token name", "token non identifié"),
]


def fr_reason(txt):
    for en, fr in REASONS:
        txt = txt.replace(en, fr)
    for k, v in NAMES.items():
        txt = re.sub(rf"\b{k}\b", v, txt)
    return txt


def translate(r):
    """Returns a short French line, or None to hide technical noise."""
    msg, lvl = r["msg"], r["lvl"]

    if msg.startswith("Read: "):                       # text provider
        tok = re.search(r"token=(\S+)", msg)
        miss = [NAMES[k] for k in FIELDS if re.search(rf"'{k}': None", msg)]
        who = tok.group(1) if tok else "?"
        return f"[LU] {who} : " + ("tous les chiffres lus" if not miss else "manque " + ", ".join(miss))
    if msg.startswith("Model raw:"):                   # LLM provider
        body = msg[len("Model raw:"):].strip()
        mm = re.search(r"\{.*\}", body, re.DOTALL)
        try:
            d = json.loads(mm.group(0)) if mm else {}
        except Exception:
            return "[LU] réponse du modèle illisible"
        miss = [NAMES[k] for k in FIELDS if d.get("metrics", {}).get(k) is None] if d.get("metrics") else []
        s = f"[MODÈLE] {d.get('intent', '?')}"
        if d.get("token"):
            s += f" {d['token']}"
        if d.get("intent") == "enter" and miss:
            s += " (chiffres manquants : " + ", ".join(miss) + ")"
        if d.get("reason"):
            s += f" - {short(str(d['reason']), 60)}"
        return s
    if msg.startswith("ENTRY REFUSED"):
        m = re.match(r"ENTRY REFUSED ?(\S*?): (.*)", msg, re.DOTALL)
        who, why = (m.group(1), m.group(2)) if m else ("", msg)
        return f"[REFUSÉ] {who} : {short(fr_reason(why), 100)}"
    if msg.startswith("ENTRY approved"):
        tok = re.search(r"'token': '([^']+)'", msg)
        usd = re.search(r"'usd': ([\d.]+)", msg)
        stp = re.search(r"'stop_pct': ([\d.]+)", msg)
        return (f"[ENTRÉE VALIDÉE] {tok.group(1) if tok else '?'} : ${usd.group(1) if usd else '?'}, "
                f"stop -{stp.group(1) if stp else '?'}%")
    if msg.startswith("EXIT approved"):
        tok = re.search(r"'token': '([^']+)'", msg)
        why = re.search(r"'reason': '([^']+)'", msg)
        return f"[SORTIE] {tok.group(1) if tok else '?'} : {why.group(1) if why else ''}"
    if "exit done, pnl" in msg:
        p = re.search(r"pnl \$(-?[\d.]+)", msg)
        return f"[RÉSULTAT] {'+' if p and float(p.group(1)) >= 0 else ''}{p.group(1) if p else '?'} $"
    if "entry recorded" in msg:
        return "[PAPER] entrée simulée enregistrée"
    if msg.startswith("LIVE trade recorded"):
        return "[LIVE] trade enregistré"
    if msg.startswith("UI BLOCKED"):
        return "[BLOQUÉ] " + short(msg[len("UI BLOCKED "):], 90)
    if "circuit breaker" in msg.lower():
        return "[STOP JOUR] coupe-circuit actif : plus d'entrée aujourd'hui"
    if msg.startswith("WARNING"):
        return "[ATTENTION] " + short(msg[8:], 100)
    if msg.startswith("Opened fomo.family"):
        mode = "LIVE" if "Mode=LIVE" in msg else "PAPER"
        return f"[DÉMARRAGE] bot lancé en mode {mode}"
    if msg.startswith("Pilot stopped"):
        return "[ARRÊT] bot arrêté"
    if lvl in ("ERROR", "WARNING") or "STOPPING" in msg:
        return f"[{'ERREUR' if lvl == 'ERROR' else 'ATTENTION'}] " + short(msg, 120)
    return None  # everything else is noise


def build_events(recs, last):
    events = []
    for r in recs:
        t = translate(r)
        if t is None:
            continue
        if events and events[-1]["text"] == t:          # collapse repeats
            events[-1]["n"] += 1
            events[-1]["t"] = r["t"]
        else:
            events.append({"t": r["t"], "day": r["day"], "text": t, "n": 1})
    return events[-last:]


def state_block(path):
    if not os.path.exists(path):
        return ["(pas encore de state.json : le bot n'a rien enregistré)"]
    try:
        s = json.load(open(path, encoding="utf-8"))
    except Exception:
        return ["(state.json illisible)"]
    return state_lines(s)


def state_lines(s):
    """Same French summary for a local or a cloud state.json. Never raises."""
    try:
        gain = s["capital"] - s["day_start_capital"]
        lines = [f"Capital : {s['capital']:.2f} $   |   Aujourd'hui : {gain:+.2f} $   |   "
                 f"Trades du jour : {s['trades_today']}"]
        pos = s.get("positions", {})
        if pos:
            for k, p in pos.items():
                lines.append(f"  Position ouverte : {k}  ${p['initial_usd'] * p['remaining_frac']:.2f}  "
                             f"(entrée {p['entry_price']}, stop -{p['stop_pct']}%)")
        else:
            lines.append("Aucune position ouverte.")
        if s.get("halted"):
            lines.append("!! Coupe-circuit actif : plus d'entrée aujourd'hui.")
        return lines
    except Exception:
        return ["(state.json illisible)"]


def trades_lines(text, last=10):
    """Last trades of trades.jsonl (one JSON per line), in French. Bad lines are skipped. Never raises."""
    rows = []
    for raw in (text or "").splitlines():
        try:
            t = json.loads(raw)
        except Exception:
            continue
        if isinstance(t, dict):
            rows.append(t)
    if not rows:
        return ["Aucun trade pour l'instant."]
    out = [f"Derniers trades ({min(last, len(rows))} sur {len(rows)}) :"]
    for t in rows[-last:]:
        try:
            when = str(t.get("ts", "?"))[:16].replace("T", " ")
            mode = str(t.get("mode", "?")).upper()
            if t.get("side") == "buy":
                out.append(f"  {when}  {mode} ACHAT  {t.get('token')}  ${float(t.get('usd', 0)):.2f}  "
                           f"(stop -{t.get('stop_pct')}%)")
            else:
                pnl = float(t.get("pnl_usd", 0))
                out.append(f"  {when}  {mode} VENTE  {t.get('token')}  {int(round(float(t.get('frac', 0)) * 100))}%  "
                           f"{'+' if pnl >= 0 else ''}{pnl:.2f} $  ({fr_reason(str(t.get('reason', '')))})")
        except Exception:
            out.append("  (ligne de trade illisible)")
    return out


# --------------------------------------------------------------------------- cloud (GitHub, branche data)
CLOUD_BASE = "https://raw.githubusercontent.com/neoniterre/fomo-pilot/data/"


def fetch_url(url, timeout=15):
    """Returns (status, text). 404 -> (404, ""). Network problem -> raises (caught by cloud_block)."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "fomo-pilot-summary", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def cloud_block(fetch=fetch_url, last=10):
    """State + last trades of the cloud bot, read from the public `data` branch (no key). Never raises."""
    def get(name):
        try:
            return fetch(CLOUD_BASE + name)
        except Exception as e:
            return None, f"{type(e).__name__}"

    out = []
    status, text = get("STOP")
    if status == 200:
        out.append("!! Arrêt d'urgence demandé (fichier STOP sur la branche data) : le bot cloud ne tourne pas.")

    status, text = get("state.json")
    if status is None:
        return out + [f"Impossible de joindre GitHub ({text}). Vérifie ta connexion internet et réessaie."]
    if status == 404:
        out.append("Pas encore d'état dans le cloud (le bot n'a encore rien sauvegardé sur la branche data).")
    elif status != 200:
        out.append(f"GitHub a répondu {status} pour state.json : réessaie dans quelques minutes.")
    else:
        try:
            s = json.loads(text)
            out += state_lines(s) if isinstance(s, dict) else ["(state.json du cloud illisible)"]
        except Exception:
            out.append("(state.json du cloud illisible)")

    out.append("-" * 64)
    status, text = get("trades.jsonl")
    if status == 200:
        out += trades_lines(text, last)
    elif status == 404:
        out.append("Aucun trade pour l'instant (pas encore de trades.jsonl).")
    elif status is None:
        out.append(f"Trades : GitHub injoignable ({text}).")
    else:
        out.append(f"Trades : GitHub a répondu {status}.")
    return out


def show_cloud(args, fetch=fetch_url):
    out = ["=" * 64, "  RÉSUMÉ DU BOT CLOUD (branche data, peut avoir ~5 min de retard)", "=" * 64]
    out += cloud_block(fetch, last=min(args.last, 30))
    out.append("=" * 64)
    print("\n".join(out))


def show(args):
    out = ["=" * 64, "  RÉSUMÉ DU BOT", "=" * 64]
    out += state_block(args.state)
    out.append("-" * 64)
    if not os.path.exists(args.log):
        out.append("pilot.log introuvable. Lance d'abord le bot.")
    else:
        recs = read_records(args.log)
        ev = build_events(recs, args.last)
        if not ev:
            out.append("Rien à afficher pour l'instant.")
        for e in ev:
            rep = f"  (x{e['n']})" if e["n"] > 1 else ""
            out.append(f"{e['t']}  {e['text']}{rep}")
    out.append("=" * 64)
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="pilot.log")
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--last", type=int, default=20)
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--cloud", action="store_true", help="résumé du bot cloud (branche data sur GitHub, sans clé)")
    a = ap.parse_args()
    run = show_cloud if a.cloud else show
    if a.watch:
        try:
            while True:
                os.system("cls" if os.name == "nt" else "clear")
                run(a)
                time.sleep(60 if a.cloud else 10)          # cloud: GitHub raw is cached anyway, no hammering
        except KeyboardInterrupt:
            pass
    else:
        run(a)
