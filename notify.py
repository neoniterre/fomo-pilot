"""
notify.py : alertes sur le téléphone via ntfy (https://ntfy.sh), gratuit, sans compte.

Le nom du canal (NTFY_TOPIC dans .env) sert de mot de passe : long et aléatoire, jamais commité.
Ne lève JAMAIS d'exception : une alerte ratée ne doit pas arrêter le bot.
Ne jamais mettre de clé API ou de donnée sensible dans un message.
"""
from __future__ import annotations

import os
import time


class Notifier:
    BASE = "https://ntfy.sh"

    def __init__(self, topic: str | None = None, dedupe_s: float = 60.0):
        self.topic = (topic or os.getenv("NTFY_TOPIC") or "").strip()
        self.dedupe_s = dedupe_s
        self.sent = {}
        self.errors = 0

    @property
    def enabled(self) -> bool:
        return bool(self.topic)

    def _skip(self, key: str, now: float) -> bool:
        """Same message within dedupe_s -> skipped (no spam during an error loop)."""
        self.sent = {k: t for k, t in self.sent.items() if now - t < 3600}
        if key in self.sent and now - self.sent[key] < self.dedupe_s:
            return True
        self.sent[key] = now
        return False

    async def send(self, title: str, message: str, priority: int = 3, tags: str = "", now: float | None = None) -> bool:
        """priority: 1 min .. 3 normal .. 5 urgent. title in plain ASCII (HTTP header)."""
        if not self.enabled:
            return False
        now = time.time() if now is None else now
        if self._skip(title + "|" + message, now):
            return False
        try:
            import httpx
            headers = {"Title": title.encode("ascii", "ignore").decode() or "fomo-pilot",
                       "Priority": str(priority)}
            if tags:
                headers["Tags"] = tags
            async with httpx.AsyncClient(timeout=10) as h:
                r = await h.post(f"{self.BASE}/{self.topic}", content=message.encode("utf-8"), headers=headers)
                r.raise_for_status()
            return True
        except Exception:
            self.errors += 1
            return False


# --- message builders (pure functions, easy to test) -------------------------------------------
def msg_entry(e: dict) -> tuple[str, str]:
    return ("PAPER entree " + str(e.get("token")),
            f"Entrée simulée {e.get('token')} : ${e.get('usd', 0):.2f}, stop -{e.get('stop_pct')}%")


def msg_exit(ex: dict, pnl: float) -> tuple[str, str]:
    sign = "+" if pnl >= 0 else ""
    return (f"PAPER sortie {ex.get('token')} {sign}{pnl:.2f}$",
            f"Sortie simulée {ex.get('token')} ({ex.get('reason')}), {int(round(ex.get('frac', 0) * 100))}% de la position. "
            f"Résultat : {sign}{pnl:.2f} $")


def msg_report(capital: float, day_start: float, trades: int, positions: list[str], halted: bool) -> tuple[str, str]:
    gain = capital - day_start
    txt = (f"Capital {capital:.2f} $ | Aujourd'hui {gain:+.2f} $ | Trades {trades}\n"
           + ("Positions ouvertes : " + ", ".join(positions) if positions else "Aucune position ouverte.")
           + ("\nCoupe-circuit actif aujourd'hui." if halted else ""))
    return "Rapport du jour", txt
