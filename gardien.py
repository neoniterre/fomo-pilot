#!/usr/bin/env python3
"""
gardien.py : garde le bot en vie sans toi (Windows ; marche aussi ailleurs pour les tests).

  - vérifie toutes les 20 s que Chrome (mode debug, port 9222) répond, sinon le relance ;
  - lance pilot.py --auto (PAPER) et le relance s'il s'arrête, avec une pause croissante ;
  - au plus --max-restarts relances par heure, ensuite il s'arrête et t'envoie une alerte ntfy ;
  - ne lance JAMAIS --live.

Usage : python gardien.py [options de pilot.py à ajouter...]
Les options par défaut sont celles de lancer_bot.bat. Arrêt : Ctrl+C (arrête aussi le bot).
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time

from dotenv import load_dotenv

from notify import Notifier

load_dotenv()
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BOT_ARGS = ["--auto", "--navigate", "--model", "claude-haiku-5-5", "--capital", "20",
                    "--min-30m", "20", "--min-1h", "50"]
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
CHROME_PROFILE = r"C:\chrome-debug"


def port_open(port: int = 9222, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class RestartLimiter:
    """At most `max_per_hour` restarts per hour; waits longer after each recent restart (30 s, 60 s, 120 s... max 10 min)."""

    def __init__(self, max_per_hour: int = 6):
        self.max, self.times = max_per_hour, []

    def _recent(self, now):
        self.times = [t for t in self.times if now - t < 3600]
        return self.times

    def allowed(self, now: float) -> bool:
        return len(self._recent(now)) < self.max

    def wait_s(self, now: float) -> float:
        return min(30 * 2 ** max(len(self._recent(now)) - 1, 0), 600)

    def record(self, now: float):
        self.times.append(now)


def sanitize_args(args: list[str]) -> list[str]:
    """The guardian never starts a live bot."""
    if any(a == "--live" or a.startswith("--live=") for a in args):
        raise SystemExit("gardien: --live est interdit.")
    return args


def find_chrome() -> str | None:
    return next((p for p in CHROME_PATHS if os.path.exists(p)), None)


def start_chrome() -> bool:
    exe = find_chrome()
    if not exe:
        return False
    subprocess.Popen([exe, "--remote-debugging-port=9222", f"--user-data-dir={CHROME_PROFILE}", "https://fomo.family"])
    return True


def start_bot(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, os.path.join(HERE, "pilot.py")] + args, cwd=HERE)


def log(msg: str):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " | " + msg
    print(line, flush=True)
    try:
        with open(os.path.join(HERE, "gardien.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


async def main(extra_args: list[str]):
    args = sanitize_args(extra_args or DEFAULT_BOT_ARGS)
    notif, limiter = Notifier(), RestartLimiter()
    bot, last_chrome_try = None, 0.0
    log("Gardien démarré (PAPER). Ctrl+C pour arrêter.")
    await notif.send("Gardien demarre", "Le gardien surveille Chrome et le bot.", priority=2, tags="shield")
    try:
        while True:
            now = time.time()
            if not port_open() and now - last_chrome_try > 120:       # Chrome debug absent
                last_chrome_try = now
                ok = start_chrome()
                log("Chrome relancé en mode debug." if ok else "Chrome introuvable, relance impossible.")
                await notif.send("Chrome relance" if ok else "Chrome introuvable",
                                 "Chrome a été relancé en mode debug (vérifie que tu es connecté à fomo)."
                                 if ok else "Impossible de relancer Chrome tout seul.", priority=4, tags="warning")
                await asyncio.sleep(15)
            if bot is None or bot.poll() is not None:
                if bot is not None:
                    log(f"Le bot s'est arrêté (code {bot.returncode}).")
                if not limiter.allowed(now):
                    log("Trop de relances en 1 h : le gardien s'arrête.")
                    await notif.send("GARDIEN ARRETE", "Le bot plante en boucle (6 relances en 1 h). "
                                     "Regarde pilot.log.", priority=5, tags="rotating_light")
                    return
                if bot is not None:
                    wait = limiter.wait_s(now)
                    log(f"Relance du bot dans {int(wait)} s.")
                    await notif.send("Bot relance", f"Le bot s'était arrêté (code {bot.returncode}), relance dans {int(wait)} s.",
                                     priority=3, tags="arrows_counterclockwise")
                    await asyncio.sleep(wait)
                limiter.record(time.time())
                bot = start_bot(args)
                log("Bot lancé.")
            await asyncio.sleep(20)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if bot is not None and bot.poll() is None:
            bot.terminate()
        log("Gardien arrêté.")


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]))
    except KeyboardInterrupt:
        pass
