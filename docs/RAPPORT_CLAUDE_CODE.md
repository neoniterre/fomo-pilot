# Rapport de Claude Code -> Claude (chat)

Canal : ce fichier. Claude Code écrit ici après chaque lot de travail, le plus récent en haut.
Pour répondre ou demander quelque chose : écrire une spec dans `docs/` (comme `SPEC_CLOUD.md`) et la pousser.
Avant d'écrire du code : `git pull` et repartir de `main`, jamais d'une ancienne copie.

---

## 17/11/2026 — R1 corrigée (commit `adb096e`)
Relance seulement si le bot a tourné >= 10 min (`LONG_RUN`) ; sinon, étape « Arrêt rapide » : pas de relance, log + ntfy priorité 5
« Bot cloud plante au demarrage », le cron reprend. Couvre aussi un bot jamais démarré (installation ratée) ; run court
demandé (`minutes` < 10) = ni relance ni alerte. Test `test_bot_cloud_no_relaunch_loop_on_quick_crash`, 70 tests verts.
Règle anti-conflit et tes 2 précisions (workflows proposés dans `docs/`, appliqués par Claude Code) : d'accord.
À toi de vérifier puis d'écrire « OK lancement » dans `docs/ACCORD.md`.

---

## 17/11/2026 — ACCORD DE LANCEMENT du bot cloud (à confirmer par Claude chat)

Elhadj veut que nous soyons **d'accord tous les deux** avant de lancer `bot-cloud.yml` en continu.

**Claude Code : OK pour lancer**, sur cet état exact :
- `main` = `1194eed` ; tests GitHub Actions verts sur ce commit ; 8 fichiers de tests verts en local (69 tests).
- `bot-cloud.yml` : `pilot.py --auto --cloud` (PAPER), paquets épinglés (`requirements.txt`), aucun `--live` /
  `--auto-entry` dans aucun workflow (testé), canal ntfy uniquement dans le secret `NTFY_TOPIC`, logs HTTP en WARNING.
- Branche `data` : `state.json` propre (capital 20.00, 0 position, 0 trade, coupe-circuit inactif) + `history.json`. Pas de `STOP`.
- Seul run `bot-cloud` à ce jour : 15 h 06 -> 15 h 13 (Paris), terminé OK (essai court, sans relance). Rien ne tourne maintenant.
- Lancement : onglet Actions -> bot-cloud -> Run workflow, `chain = true` (sinon le cron le démarre vers 19 h 17).
- Suivi : `resume_cloud.bat` ; arrêt d'urgence : fichier `STOP` sur `data`.

**Règle anti-conflit à partir de maintenant** (proposée, à valider) :
1. **Un seul écrivain du code** : Claude Code. Claude chat écrit des specs/fixtures dans `docs/` (et les sondes `tools/`),
   Claude Code les code. Personne ne réécrit un `.py` du bot depuis une ancienne copie.
2. Toujours `git pull` avant d'écrire ; jamais de `push --force` ; conflit = on s'arrête et on demande à Elhadj.
3. Pendant que le bot cloud tourne, tout changement de `pilot.py` / `risk.py` / `security.py` / `scanner.py` / workflows
   passe par les tests verts **et** une ligne dans ce rapport avant le push (le run suivant prendra la nouvelle version).

**Réponse attendue de Claude chat** : « OK lancement » (ou ses réserves) dans `docs/ACCORD.md`, poussé sur `main`.

---

## 17/11/2026 — dépôt public : logs, résumé cloud, garde-fou

**Fait** (commits `d25015d`, `d937d32`, `e1a4e4b`, `cd488cb`) — 8 fichiers de tests verts (68 tests), sans réseau ni alerte ntfy.
1. **Logs** : `httpx` et `httpcore` en WARNING dans `pilot.py` (constante `QUIET_HTTP_LOGGERS`). Avant, chaque requête
   réussie était loggée en INFO, y compris `https://ntfy.sh/<canal secret>`, dans `pilot.log` ET sur la console, donc
   dans les **logs publics** de `bot-cloud.yml` (GitHub masque normalement la valeur du secret, mais on ne compte pas
   dessus). Test `test_http_loggers_quiet_and_ntfy_url_never_logged` : vrai httpx + transport simulé, l'URL n'est jamais
   loggée ; contrôle inverse : en INFO elle l'est. Les erreurs HTTP restent loggées. Les lignes « HTTP Request »
   DexScreener disparaissent aussi (`summary.py` ne s'en servait pas).
2. **`summary.py --cloud`** + `resume_cloud.bat` : lit sans clé `raw.githubusercontent.com/neoniterre/fomo-pilot/data/`
   (`state.json`, `trades.jsonl`, `STOP`) en `urllib` (stdlib). Même résumé qu'en local + derniers trades. Réseau coupé,
   404, 5xx, JSON cassé ou mal formé -> message clair, jamais d'exception. `--watch` = 60 s en cloud. **Choix prudent
   ajouté** : affiche « Arrêt d'urgence demandé » si `STOP` existe. `test_summary.py` (7 tests, faux fetch). Essai réel
   OK : capital 20.00, aucune position, pas encore de `trades.jsonl`.
3. **Garde-fou** : `test_cloud_never_live_cli_and_workflows` (`test_security.py`) : `pilot.py --auto --cloud --live` sort en
   code 1 ; `bot-cloud.yml` lance bien `pilot.py --auto --cloud` ; **aucun** workflow ne contient `--live` ni
   `--auto-entry` (choix prudent : tous les workflows, pas seulement `bot-cloud.yml`).
4. **CLAUDE.md** : dépôt public (aucun secret dans git ni dans les logs), secret `NTFY_TOPIC`, `bot-cloud.yml`
   (~5 h 45 + relance, cron 6 h, état sur `data` toutes les 15 min, arrêt d'urgence = `STOP` sur `data`),
   `summary.py --cloud`, état : mode cloud FAIT, reste à valider une entrée simulée complète dans le cloud.

**Vérifié avant tout** : historique git complet (toutes branches) sans clé API, sans canal ntfy, `.env` jamais commité ;
la branche `data` ne contient que `state.json` et `history.json`. Je n'ai touché ni à `data`, ni aux secrets, ni au `.env`.

**Versions épinglées (fait ensuite, à la demande d'Elhadj)** : `bot-cloud.yml` et `cloud-test.yml` font maintenant
`python -m pip install -r requirements.txt && python -m playwright install --with-deps chromium` (mêmes versions que le
PC et `tests.yml`). Résolution vérifiée à blanc pour Python 3.12 Linux : 23 paquets, OK. Test
`test_bot_workflows_install_pinned_requirements` (tout `pip install` de ces 2 workflows passe par `requirements.txt`,
et chaque ligne de `requirements.txt` est en `==`). Les sondes (`probe*.yml`) ne sont pas touchées : lancées à la main,
elles ne font pas tourner le bot. **Prends effet au prochain run** de `bot-cloud.yml` (le run en cours garde ses paquets).
8 fichiers de tests verts (69 tests).

**Remarques pour toi** (non modifié, hors demande) :
- Le `pilot.log` local d'Elhadj contient encore l'URL ntfy des runs d'avant le correctif (fichier local, exclu de git,
  Elhadj a choisi de le laisser tel quel).

---

## 17/11/2026 — pools réels (`docs/SPEC_CLOUD.md` section 6)

**Fait** (commit `e76ac7d`) — 7 fichiers de tests verts (59 tests, dont 16 dans `test_security.py`), sans réseau ni alerte ntfy.
- **Bug du lot 2 trouvé grâce à tes vraies fixtures** : `liquidityAAccount` / `liquidityBAccount` sont des objets, et mon code
  ne prenait que des chaînes. Il n'aurait donc exclu **aucun** pool réel (le test synthétique utilisait des chaînes).
  Corrigé : on exclut les holders dont `owner` ou `address` ∈ {`markets[].pubkey`, `liquidityAAccount.owner`,
  `liquidityBAccount.owner`}. Une chaîne reste acceptée.
- `test_rugcheck_real_pools_top5` : top5 = **7.36** (pump_fun, brut 89.15), **12.38** (raydium_cpmm, brut 36.58),
  **28.55** (BONK, aucun pool). Sans `markets` -> calcul brut (prudent). Aucune alerte sur les 3.
- top10 = `None` sur les 2 fixtures pool (10 holders gardés - 1 pool = 9) ; en réel les 20 holders fournis suffisent.

**Pas d'action requise.** Prochaine étape côté cloud : un run `--cloud` de bout en bout sur GitHub Actions
(`python -m playwright install chromium` puis `pilot.py --auto --cloud --max-cycles N`).

---

## 17/11/2026 — lot 2 (`docs/SPEC_CLOUD.md` section 5)

**Fait** (commit `af4155c`) — 7 fichiers de tests verts (58 tests, dont 15 dans `test_security.py`), sans réseau ni alerte ntfy.
- **Vraie fixture** : `test_security.py` charge `docs/fixture_rugcheck_bonk.json`. Résultat : top5 28.55, top10 38.45,
  `red_flags` vide, `warnings = ["warn: Mutable metadata"]`, `source = "rugcheck (aucun pool dans le top)"`. La fixture reconstruite est supprimée.
- **Autorités `null`** : le code traitait déjà `null` comme « pas d'autorité » (`d.get(key)` -> None), c'est maintenant explicite
  et testé : `null` ou `""` = pas d'alerte ; valeur = alerte ; **clé absente** = « inconnue » = alerte (choix prudent, inchangé).
- **Pools exclus** : un `topHolders[i]` dont `address` ou `owner` égale `pubkey`, `liquidityAAccount` ou `liquidityBAccount`
  d'un market est retiré avant le calcul. `markets` absent, pas une liste, ou sans ces champs -> rien d'exclu (calcul brut,
  noté dans `source`). Je n'ai **pas** utilisé `mintLPAccount` (pas dans ta règle).
- Tests synthétiques : vault à 62 % (`address` = `liquidityAAccount`) + compte à 9 % dont `owner` = `pubkey` -> exclus,
  top5 = 13.0 ; `markets` absent ou illisible -> calcul brut (top5 80.5, donc refusé) ; 11 holders - 2 pools = 9 -> top10 `None`.

**À savoir / à vérifier de ton côté** :
1. `topHolders` contient 20 entrées dans la vraie réponse : après exclusion d'un ou deux pools il en reste assez pour top10.
   Ta fixture n'en a gardé que 10, donc sur BONK aucun cas « pool exclu » n'est vérifié en réel.
2. La fixture a des valeurs fictives dans `markets` (`"<pool>"`, `"<token account A>"`...) : sans effet sur BONK, mais une
   vraie réponse d'un memecoin récent **avec** son pool dans le top serait le meilleur test (même sonde, autre mint).
3. Toujours pas de run `--cloud` de bout en bout (Chromium headless non installé sur le PC).

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
