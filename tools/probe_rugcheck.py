"""Sonde : vraie réponse RugCheck (fixture) + les pools/LP sont-ils identifiables dans topHolders ?"""
import json

import httpx

MINTS = {"BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"}


def walk(o, out, path=""):
    """collects every string value with its path (to find holder addresses inside markets)"""
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, out, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, out, f"{path}[]")
    elif isinstance(o, str) and len(o) > 30:
        out.setdefault(o, set()).add(path)


for name, mint in MINTS.items():
    d = httpx.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=20).json()
    print("[FIXTURE]", json.dumps({k: d.get(k) for k in ("mint", "rugged", "freezeAuthority", "mintAuthority",
                                                         "score_normalised", "totalHolders", "risks")}))
    th = d["topHolders"]
    print("[FIXTURE] topHolders(12):", json.dumps([{k: h.get(k) for k in ("address", "pct", "owner", "insider")} for h in th[:12]]))
    idx = {}
    walk({k: v for k, v in d.items() if k not in ("topHolders",)}, idx)
    for i, h in enumerate(th[:20]):
        hits = sorted(idx.get(h.get("address"), set()) | idx.get(h.get("owner"), set()))
        if hits:
            print(f"[POOL?] rang {i + 1} pct={h['pct']:.2f} address/owner trouvés dans : {hits}")
    m = (d.get("markets") or [{}])[0]
    print("[MARKET0 clés]", sorted(m.keys()), "| lp clés:", sorted((m.get("lp") or {}).keys()))
