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

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(URL, wait_until="domcontentloaded", timeout=40000)
        try:
            pg.wait_for_function("document.body && document.body.innerText.includes('Position in this view')",
                                 timeout=25000)
        except Exception as e:
            print("[HEADLESS] attente marqueur :", str(e)[:100])
        txt = pg.evaluate("document.body ? document.body.innerText : ''")
        items = parse_fomo_list(txt)
        print(f"[HEADLESS] len={len(txt)} marqueur={'Position in this view' in txt} tokens lus={len(items)}")
        print("[HEADLESS] exemples:", [(i['symbol'], i['price'], i['change_24h_pct']) for i in items[:5]])
        if not items:
            print("[HEADLESS] début de page :", repr(txt[:400]))
        b.close()


if __name__ == "__main__":
    main()
