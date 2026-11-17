"""Sonde : montre ce que RugCheck (Solana) et GoPlus (EVM) renvoient VRAIMENT, sans clé.
Usage : python tools/probe_security.py   (réseau requis ; GitHub Actions ou ton PC)
Aucune clé, aucune écriture. Sert à vérifier les champs avant de coder le mode cloud."""
import json
import sys
import time

import httpx

SOL_MINT = "So11111111111111111111111111111111111111112"          # wSOL (grosse, propre)
SOL_MEME = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"         # BONK
EVM = [("1", "0xdAC17F958D2ee523a2206206994597C13D831ec7"),        # USDT Ethereum
       ("56", "0x55d398326f99059fF775485246999027B3197955")]       # USDT BSC


def show(title, r):
    print(f"\n=== {title} -> HTTP {r.status_code}  limits: " +
          str({k: v for k, v in r.headers.items() if "limit" in k.lower() or "retry" in k.lower()}))
    try:
        return r.json()
    except Exception:
        print(r.text[:300])
        return None


def main():
    h = httpx.Client(timeout=20, headers={"User-Agent": "fomo-pilot-probe"})
    for mint in (SOL_MEME,):
        d = show(f"RugCheck report {mint}", h.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"))
        if d:
            print("clés :", sorted(d.keys()))
            th = d.get("topHolders") or []
            print("topHolders :", len(th), "| exemple :", json.dumps(th[:2])[:300])
            print("somme pct top5 / top10 :", round(sum(x.get("pct", 0) for x in th[:5]), 2),
                  round(sum(x.get("pct", 0) for x in th[:10]), 2))
            print("risks :", [(x.get("name"), x.get("level")) for x in d.get("risks") or []])
            print("score_normalised :", d.get("score_normalised"), "| rugged :", d.get("rugged"))
        d = show(f"RugCheck summary {mint}", h.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"))
        if d:
            print(json.dumps(d)[:400])
        time.sleep(1)
    for chain, addr in EVM:
        d = show(f"GoPlus EVM chain {chain}",
                 h.get(f"https://api.gopluslabs.io/api/v1/token_security/{chain}", params={"contract_addresses": addr}))
        if d:
            res = (d.get("result") or {}).get(addr.lower()) or {}
            print("code/message :", d.get("code"), d.get("message"))
            print("champs utiles :", {k: res.get(k) for k in ("holder_count", "is_honeypot", "buy_tax", "sell_tax",
                                                              "is_mintable", "owner_address", "lp_holder_count")})
            hs = res.get("holders") or []
            print("holders :", len(hs), "| exemple :", json.dumps(hs[:2])[:300])
        time.sleep(1)
    d = show("GoPlus Solana", h.get("https://api.gopluslabs.io/api/v1/solana/token_security",
                                    params={"contract_addresses": SOL_MEME}))
    if d:
        print(json.dumps(d)[:700])


if __name__ == "__main__":
    sys.exit(main())
