"""Sonde : trouve de VRAIS memecoins Solana récents dont un pool/LP apparaît dans topHolders (RugCheck),
pour valider la règle d'exclusion des pools. Lecture seule, sans clé."""
import json
import time

import httpx

H = httpx.Client(timeout=20, headers={"User-Agent": "fomo-pilot-probe"})
SHAPE = []
POOL_KEYS = ("pubkey", "liquidityAAccount", "liquidityBAccount", "mintLPAccount")


def candidates():
    seen, out = set(), []
    for url in ("https://api.dexscreener.com/token-profiles/latest/v1",
                "https://api.dexscreener.com/token-boosts/latest/v1",
                "https://api.dexscreener.com/token-boosts/top/v1"):
        try:
            for x in H.get(url).json():
                if x.get("chainId") == "solana" and x.get("tokenAddress") not in seen:
                    seen.add(x["tokenAddress"]); out.append(x["tokenAddress"])
        except Exception as e:
            print("[POOLS] liste", url, e)
    return out


def main():
    cands = candidates()
    print(f"[POOLS] {len(cands)} tokens Solana candidats")
    found = 0
    for mint in cands[:14]:
        time.sleep(1.3)
        try:
            r = H.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
            if r.status_code != 200:
                print("[POOLS]", mint[:8], "HTTP", r.status_code); continue
            d = r.json()
        except Exception as e:
            print("[POOLS]", mint[:8], "erreur", e); continue
        pool_ids = {}
        for m in d.get("markets") or []:
            for k in POOL_KEYS:
                v = m.get(k)
                if isinstance(v, str) and v:
                    pool_ids[v] = k
                elif isinstance(v, dict):
                    if not SHAPE:
                        SHAPE.append(1)
                        print("[POOLS] forme d'un champ objet", k, ":", json.dumps(v)[:400])
                    for sub, sv in v.items():
                        if isinstance(sv, str) and len(sv) > 30:
                            pool_ids[sv] = f"{k}.{sub}"
        th = d.get("topHolders") or []
        hits = []
        for i, h in enumerate(th[:20]):
            for fld in ("address", "owner"):
                if h.get(fld) in pool_ids:
                    hits.append({"rang": i + 1, "pct": round(h.get("pct", 0), 2), "holder_field": fld, "matches": pool_ids[h[fld]]})
        sym = (d.get("tokenMeta") or {}).get("symbol")
        top5 = round(sum(h.get("pct", 0) for h in th[:5]), 2)
        print(f"[POOLS] {sym} {mint[:8]} holders={len(th)} top5_brut={top5} marchés={len(d.get('markets') or [])} pools_dans_top={hits}")
        if hits and found < 2:
            found += 1
            keep = {k: d.get(k) for k in ("mint", "rugged", "freezeAuthority", "mintAuthority", "score_normalised", "totalHolders", "risks")}
            keep["topHolders"] = [{k: h.get(k) for k in ("address", "pct", "owner", "insider")} for h in th[:10]]
            keep["markets"] = [{k: m.get(k) for k in ("pubkey", "marketType", "liquidityAAccount", "liquidityBAccount", "mintLPAccount")}
                               for m in (d.get("markets") or [])[:3]]
            print("[POOLFIX]", json.dumps(keep))
    print("[POOLS] fin, tokens avec pool dans le top :", found)


if __name__ == "__main__":
    main()
