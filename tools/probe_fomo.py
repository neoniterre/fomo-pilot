"""Sonde : les listes publiques fomo se lisent-elles SANS Chrome de l'utilisateur (serveur / GitHub Actions) ?
Teste (1) un simple GET HTTP, (2) Chromium headless Playwright. Lecture seule, aucune connexion."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scanner import parse_fomo_list  # noqa: E402

URL = "https://fomo.family/top-movers"


def main():
    import httpx
    try:
        r = httpx.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
        print(f"[HTTP] status={r.status_code} len={len(r.text)} marqueur={'Position in this view' in r.text}")
    except Exception as e:
        print("[HTTP] erreur", e)

    import re
    import time
    try:
        html = r.text
        print("[HTTP] __NEXT_DATA__:", "__NEXT_DATA__" in html, "| self.__next_f:", "self.__next_f" in html,
              "| '24h change' dans le HTML:", "24h change" in html, "| '$' prix:", len(re.findall(r'"price"', html)))
        i = html.find("Position in this view")
        print("[HTTP] contexte 'Position':", repr(html[max(i - 100, 0):i + 300]) if i >= 0 else "absent")
    except Exception as e:
        print("[HTTP] analyse", e)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1400, "height": 900}, bypass_csp=True)
        pg = ctx.new_page()
        pg.goto(URL, wait_until="domcontentloaded", timeout=40000)
        txt, t0 = "", time.time()
        while time.time() - t0 < 30:                      # polling sans eval de chaîne (CSP de fomo)
            txt = pg.inner_text("body")
            if "Position in this view" in txt:
                break
            pg.mouse.wheel(0, 1500)                       # certaines listes se chargent au défilement
            time.sleep(1.5)
        items = parse_fomo_list(txt)
        print(f"[HEADLESS] attendu {time.time() - t0:.0f}s len={len(txt)} marqueur={'Position in this view' in txt} tokens lus={len(items)}")
        print("[HEADLESS] exemples:", [(i['symbol'], i['price'], i['change_24h_pct']) for i in items[:5]])
        if not items:
            print("[HEADLESS] fin de page :", repr(txt[-500:]))
        b.close()


if __name__ == "__main__":
    main()
