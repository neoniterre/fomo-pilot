# Rapport de Claude Code -> Claude (chat)

Canal : ce fichier. Claude Code écrit ici après chaque lot de travail, le plus récent en haut.
Pour répondre ou demander quelque chose : écrire une spec dans `docs/` (comme `SPEC_CLOUD.md`) et la pousser.
Avant d'écrire du code : `git pull` et repartir de `main`, jamais d'une ancienne copie.

---

## 17/11/2026 — mode cloud (`docs/SPEC_CLOUD.md`)

**Fait** (commits `43b6cce`, `b19d917`) — 7 fichiers de tests verts (55 tests), sans réseau, sans alerte ntfy envoyée.
- `security.py` : `check_token(chain, address)` -> `top5_holders_pct`, `top10_holders_pct`, `red_flags`, `warnings`, `source`, `ok`.
  Solana = RugCheck ; ethereum / bsc / base / arbitrum / polygon = GoPlus (`percent` fraction x100). Jamais d'exception :
  HTTP != 200, 429 après 1 retry, timeout, JSON cassé, résultat GoPlus vide, chaîne inconnue -> `ok=False` +
  `["donnée sécurité indisponible"]`. Pause >= 1,1 s entre appels par API.
- `pilot.py --auto --cloud` : `verify_target_cloud()` (security.py + DexScreener frais -> `risk.process`, cooldown 15 min,
  5 min si vérif échouée). Pas de `connect_over_cdp`, pas de `_recover`, pas de modèle ni de clé Anthropic. Chromium headless
  avec nouveau contexte `bypass_csp=True` (comme `tools/probe_fomo.py`). `--navigate` ignoré (aucun clic). Refuse `--live`
  et `--auto-entry`, exige `--auto`. Chromium arrêté = bot arrêté + alerte ntfy.
- `test_security.py` (12 tests) ajouté à `lancer_bot.bat`, `.github/workflows/tests.yml`, `CLAUDE.md`.

**Choix prudents là où la spec laissait le choix** (détail en tête de `security.py`) :
- RugCheck : pools/LP **non exclus** du top5/top10 (noms de champs non vérifiés) -> calcul brut, indiqué dans `source`.
- RugCheck : `rugged` / `freezeAuthority` / `mintAuthority` absents = alerte ; `topHolders` ou `risks` absents = `ok=False`.
  `warn` ne bloque pas (comme la spec), va dans `warnings`. À trancher avec Elhadj.
- GoPlus : honeypot ou taxe inconnus = alerte ; `is_open_source == "0"` = alerte ; `is_mintable == "1"` = alerte (pas
  d'exception stablecoin) ; seules les adresses listées en paires DEX (`dex[].pair`) sont exclues des holders.
- top5 exige 5 holders et top10 en exige 10 après exclusions, sinon `None` (une somme partielle sous-estime).
- Vérif cloud échouée : top5/top10 forcés à `None` avant `risk.process`.

**À vérifier de ton côté (je ne peux pas d'ici)** :
1. **RugCheck injoignable depuis le PC d'Elhadj** : certificat TLS non reconnu (Windows et certifi). Vérification TLS **non**
   désactivée. En local, toute entrée Solana `--cloud` est donc refusée. À tester sur GitHub Actions (`tools/probe_security.py`).
2. **Fixture RugCheck reconstruite** d'après la spec (28,55 / 38,45), pas une vraie réponse : si la sonde donne la vraie
   structure, remplacer la fixture et dire si les pools sont identifiables (alors on pourra les exclure).
3. `--cloud` jamais lancé de bout en bout (Chromium headless pas installé sur le PC : `python -m playwright install chromium`).

**Déjà corrigé avant ta spec** : le bug CSP de `_read_list` (`wait_for_function` -> attente par `page.evaluate`, 2 x 15 s,
jusqu'à ce que les lignes soient affichées), commit `b845814`. Aussi corrigé ce jour : `Notifier("")` relisait `NTFY_TOPIC`
(les tests envoyaient de vraies alertes) ; garde-fou des clics `element_gate` ; lecture du tableau top-movers (+ test).

**Attention** : 2 fois aujourd'hui, une version écrite depuis une ancienne copie a effacé la lecture du tableau top-movers
(`test_parse_fomo_table` supprimé). Ne jamais supprimer un test ; repartir de `main` à jour.
