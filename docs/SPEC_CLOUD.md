# Spec : mode cloud (sans Chrome ni PC) — à coder par Claude Code

Objectif : remplacer la vérification par Chrome (top holders + alertes lus par un modèle) par des API gratuites sans clé,
pour pouvoir tourner sur un serveur ou GitHub Actions. Principe inchangé : **fail-closed** (donnée illisible = `None` = entrée refusée).
**Paper uniquement.** Ne pas toucher au `.env`. Tests sans réseau (fixtures = vraies réponses ci-dessous). 5 tests existants à garder verts.

## 1. `security.py` (nouveau)
`async def check_token(chain, address) -> dict` renvoie `{"top5_holders_pct", "top10_holders_pct", "red_flags": [...], "source", "ok": bool}`.
Jamais d'exception ; en cas d'erreur : `ok=False`, valeurs `None`, `red_flags` = `["donnée sécurité indisponible"]`.

### Solana -> RugCheck (sans clé), vérifié le 17/11/2026
- `GET https://api.rugcheck.xyz/v1/tokens/{mint}/report` (HTTP 200). Header de limite : `x-rate-limit-limit: 15`. Respecter une pause (>= 1 s entre appels), retry 1x sur 429.
- Champs : `topHolders` = liste de 20 `{address, pct, insider, owner, ...}` (pct en % du supply) ; `risks` = `[{name, level ("warn"|"danger"|...), description}]` ;
  `rugged` (bool) ; `score_normalised` (0-100, plus haut = plus risqué ; BONK = 7) ; `totalHolders` ; `freezeAuthority` / `mintAuthority` ;
  `markets`, `lockers`, `totalMarketLiquidity`.
- Résumé léger : `GET .../report/summary` -> `{risks, score_normalised, lpLockedPct}`.
- top5 = somme des `pct` des 5 premiers, top10 = des 10 premiers. IMPORTANT : exclure du calcul les adresses de pools/LP si le champ le permet
  (sinon un pool compte comme « holder »). Si impossible à distinguer : garder le calcul brut (conservateur) et le noter dans `source`.
- `red_flags` : `rugged == True`, tout risque de niveau `danger`, `freezeAuthority` ou `mintAuthority` non nuls, holders `insider` > 0.
  (À discuter avec Elhadj : les `warn` simples comme « Mutable metadata » ne bloquent pas.)

### EVM -> GoPlus (sans clé), vérifié le 17/11/2026
- `GET https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={addr}` ; chain_id : ethereum `1`, bsc `56`, base `8453`, arbitrum `42161`, polygon `137`.
- Réponse : `{"code":1,"message":"OK","result":{"<addr minuscule>": {...}}}`. Champs : `holder_count` (str), `holders` = 10 `{address, percent ("0.166" = 16.6 %, FRACTION), is_contract, is_locked}`,
  `is_honeypot` ("0"/"1"), `buy_tax`/`sell_tax` (fraction, str), `is_mintable`, `owner_address`, `hidden_owner`, `can_take_back_ownership`, `cannot_sell_all`, `is_blacklisted`, `transfer_pausable`.
- ATTENTION unités : `percent` est une fraction -> multiplier par 100. Les valeurs sont des chaînes.
- `red_flags` : `is_honeypot == "1"`, `cannot_sell_all`, `hidden_owner`, taxe > 10 %, `is_blacklisted`, `can_take_back_ownership`, `transfer_pausable` ;
  `is_mintable == "1"` -> flag (sauf stablecoins : non pertinent pour des memecoins).
- Ne compter dans top5/top10 que les holders `is_contract == 0` et `is_locked == 0` ? **Non** : rester conservateur (tout compter) sauf adresses de pool connues ; documenter.
- GoPlus Solana : format différent, ne pas utiliser (RugCheck suffit).
- Chaîne inconnue (hors liste) : `ok=False` -> entrée refusée.

## 2. `pilot.py` : option `--cloud`
- Avec `--cloud` : `verify_target` n'ouvre plus Chrome ; il appelle `security.check_token(tgt["chain"], tgt["address"])`, puis la suite est identique
  (métriques DexScreener fraîches, `risk.process(decision)`, cooldown).
- `scan_fomo` : sans Chrome, lire les listes fomo publiques autrement. **Question ouverte** : `_read_list` utilise Playwright ; en cloud il faut soit un Chromium headless
  (Playwright, sans login car les listes /top-movers et /new sont publiques), soit une source alternative (DexScreener boosts / trending). Tester d'abord headless sur GitHub Actions.
- En mode `--cloud` : pas de `connect_over_cdp`, pas de `_recover`, pas de clé Anthropic requise. `--auto --cloud` toujours refusé avec `--live`.
- Alertes ntfy déjà en place (`notify.py`).

## 3. Tests (`test_security.py`, sans réseau)
- Fixture RugCheck (top holders 28.55 % top5 / 38.45 % top10 pour BONK au 17/11/2026) -> `top5_holders_pct == 28.55`, `top10_holders_pct == 38.45` (arrondi 2 décimales).
- Fixture GoPlus (USDT : `percent` fraction) -> conversion en %. Honeypot, taxe élevée, chaîne inconnue, JSON cassé, HTTP 429, timeout -> `ok=False` ou flag, jamais d'exception.
- Ajouter le test à `lancer_bot.bat`, `.github/workflows/tests.yml`, `CLAUDE.md`.

## 3 bis. Résultat de la sonde fomo (GitHub Actions, 17/11/2026) — question ouverte RÉSOLUE
- Un simple GET HTTP ne marche pas (la liste n'est pas dans le HTML). **Chromium headless Playwright marche sans login** : `tools/probe_fomo.py`
  lit 20 tokens en ~2 s avec `new_context(bypass_csp=True)` + `inner_text("body")` en boucle (pas de `wait_for_function`).
- **BUG probable dans `pilot.py` (`_read_list`)** : `page.wait_for_function("<chaîne JS>")` échoue sur fomo avec
  `EvalError: Evaluating a string as JavaScript violates the following Content Security Policy`. Ça peut expliquer les « page illisible / 0 token » vus en local.
  Corriger : remplacer par une boucle `inner_text("body")` (+ petit défilement `mouse.wheel`) jusqu'à voir « Position in this view », timeout ~30 s.
  Dans le Chrome de l'utilisateur on ne peut pas mettre `bypass_csp` sur un contexte existant : la boucle de polling suffit.
- Donc pour `--cloud` : Chromium headless (nouveau contexte, `bypass_csp=True`), jamais de connexion à fomo.

## 4. Hors périmètre (c'est Elhadj/Claude chat qui s'en occupe)
Choix du serveur, GitHub Actions « tick » planifié, stockage de l'état, budget, passage en live.

## 5. Suite (Claude chat, 17/11/2026 après relecture de ton compte rendu) — lot 2
1. **RugCheck est joignable depuis GitHub Actions** (HTTP 200, sans clé) : le souci de certificat est propre au PC d'Elhadj. Ne rien désactiver. En local, rester fail-closed.
2. **Vraie fixture** : `docs/fixture_rugcheck_bonk.json` (réponse réelle, tronquée). Remplacer la fixture reconstruite de `test_security.py` par celle-ci
   (attendu : top5 = 28.55, top10 = 38.45, `rugged` False, `freezeAuthority`/`mintAuthority` = `null` -> PAS d'alerte, un `warn` -> `warnings` seulement).
   Attention : dans la vraie réponse `freezeAuthority`/`mintAuthority` sont présents avec valeur `null` (pas absents) : ton code doit traiter `null` = pas d'autorité.
3. **Pools/LP identifiables** : un market RugCheck a `pubkey`, `liquidityAAccount`, `liquidityBAccount`, `mintLPAccount`... et un holder de pool a `address` = compte de token du pool.
   Exclure des holders tout `topHolders[i]` dont `address` ou `owner` égale un `pubkey`, `liquidityAAccount` ou `liquidityBAccount` d'un market.
   Pas observé sur BONK (aucun pool dans son top 20) : écrire un test avec une fixture synthétique. Si le champ est absent/inconnu -> garder le calcul brut (prudent).
   Pourquoi c'est important : sur un memecoin récent, la courbe/le pool détient souvent 30-90 % du supply ; en calcul brut le bot refuserait presque tout.
4. Garder les 7 fichiers de tests verts, commiter, pousser, et mettre à jour `docs/RAPPORT_CLAUDE_CODE.md`.

## 6. Pools : VRAIES réponses RugCheck (17/11/2026) — répond à ta remarque du lot 2
Sonde `tools/probe_pools.py` sur 14 memecoins Solana récents : **7 sur 14 ont un pool/courbe dans leur top holders, toujours au rang 1, entre 6 % et 83 % du supply.**
Le calcul brut aurait donc refusé la moitié des memecoins récents à cause de leur pool. Fixtures réelles :
- `docs/fixture_rugcheck_pool_pumpfun.json` (ADA, marché `pump_fun`) : rang 1 = 82,67 % = la courbe ; top5 brut 89,15 %, sans pool ~ 6,5 %.
- `docs/fixture_rugcheck_pool_raydium.json` (OGS, marché `raydium_cpmm`) : rang 1 = 26,36 % = le pool ; top5 brut 36,58 %.
**Règle vérifiée** : `markets[].liquidityAAccount` et `liquidityBAccount` sont des OBJETS `{mint, owner, amount, ...}` (pas des chaînes).
`topHolders[i].owner` du pool == `liquidityAAccount.owner` == `liquidityBAccount.owner` (== `markets[].pubkey` en pump_fun, == `mintLPAccount.mintAuthority` en raydium_cpmm).
-> Exclure tout `topHolders[i]` dont `owner` (ou `address`) ∈ {`markets[].pubkey`, `markets[].liquidityAAccount.owner`, `markets[].liquidityBAccount.owner`}.
Garder la prudence : si `markets` est absent/illisible -> calcul brut ; il faut toujours >= 5 holders restants pour le top5 (20 fournis, donc OK), >= 10 pour le top10.
Tests : les 2 fixtures réelles (attendus calculables à partir des fichiers) + BONK (aucun pool exclu, 28,55 / 38,45).
