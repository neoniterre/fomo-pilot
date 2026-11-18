# fomo-pilot

Bot de **paper trading** (simulation) de memecoins pour fomo.family. Propriétaire : Elhadj (France, parle français
décontracté, veut des réponses **courtes** et des corrections appliquées directement, sans longues explications).
Mots d'ordre : **efficacité, rapidité, prévoyance**.

## Règles absolues
- **Paper uniquement.** Ne jamais lancer ni activer `--live`, ne jamais exécuter de vrai trade, ne jamais cliquer
  Buy / Sell / Confirm / Swap / Withdraw / Transfer. `--auto` refuse déjà `--live`, ne pas lever ce garde-fou.
- **Ne jamais toucher au `.env`, ne jamais afficher ni commiter une clé API.** Ne jamais coller de clé dans un message.
- **Le dépôt GitHub est PUBLIC** (neoniterre/fomo-pilot) : aucune clé, aucun canal ntfy, aucun secret dans git, ni dans
  les logs (les logs GitHub Actions sont publics aussi). Les secrets vont dans les *secrets GitHub* (`NTFY_TOPIC`) ou le `.env`.
  `httpx`/`httpcore` restent en WARNING dans `pilot.py` (sinon l'URL ntfy, donc le canal, est loggée).
- Ne jamais écrire sur la branche `data` (état du bot cloud) ni modifier les secrets GitHub.
- **Fail-closed** : un chiffre illisible ou manquant = `None` = entrée refusée par `risk.py`. Ne jamais estimer ni deviner.
- **Les desk rules vivent dans `risk.py`** (code), pas dans un prompt. Ne les assouplir que si Elhadj le demande
  explicitement (option CLI `--min-30m`, `--min-1h` pour les seuils de momentum).
- Les chiffres viennent du **code** (DexScreener), jamais du modèle. Le modèle ne fait que naviguer, lire le top
  holders et lister les alertes de la page.

## Architecture
| Fichier | Rôle |
|---|---|
| `risk.py` | Desk rules v4 : filtres d'entrée, taille de position (risque/stop ; option de TEST `gap_buffer_pct` = risque/(stop+marge), et `exit_slippage_pct` = sorties papier X % sous le prix observé, **0 par défaut = comportement historique**), sorties (TP1/TP2/stop/trailing/volume), coupe-circuit -3 %/jour, max trades. État dans `state.json`. Garde-fous clics : `ui_gate` (texte du sélecteur) puis `element_gate` (texte RÉEL de l'élément, du bouton parent et du submit du formulaire, juste avant le clic). Ne jamais les affaiblir. |
| `scanner.py` | Listes publiques fomo (`parse_fomo_list`), client DexScreener, `resolve_token` (association symbole -> token par prix ±10 % et dominance de liquidité), métriques, `PriceHistory` (variation 30 min calculée par nos relevés), `VolumeTracker`, `save_history` / `load_history` (`history.json`). |
| `reader.py` | Lecture du texte de page par code, variation BTC 1h (Binance -> Kraken -> CoinGecko). |
| `pilot.py` | Boucle principale. Modes : texte (gratuit), `anthropic`/`xai` (modèle lit l'écran), `--auto` (scan -> filtres code -> vérif page -> entrée simulée). Si Chrome est fermé : surveille les positions via DexScreener et retente la connexion toutes les 30 s pendant `--reconnect-min` minutes (défaut 30), puis s'arrête. `--auto --cloud` : sans Chrome debug ni modèle ni clé Anthropic, listes fomo publiques en Chromium headless, holders/alertes via `security.py` ; refuse `--live`/`--auto-entry`, exige `--auto`, ignore `--navigate` (aucun clic), pas de reconnexion (Chromium arrêté = bot arrêté + alerte). **Positions ouvertes : boucle dédiée** (`position_watcher`) toutes les `--watch-interval` s (défaut et minimum 5), séparée du scan ; sur HTTP 429 DexScreener : x2 jusqu'à 60 s puis retour à 5 s. **Prix de sortie = pool principal** (le plus liquide), pas la moyenne multi-pools ; si le pool principal change : min(nouveau principal, moyenne). Prix d'entrée aussi sur le pool principal (même base). Trace : `position_trace.jsonl` (à côté de `state.json`, une ligne par position et par relevé : prix utilisé, prix du pool principal, moyenne, variation vs entrée, nb de pools, liquidité, relevé manqué, fermé), exclu de git. |
| `security.py` | Mode cloud : `check_token(chain, address)` -> top5/top10 holders + `red_flags`. Solana = RugCheck, EVM (ethereum, bsc, base, arbitrum, polygon) = GoPlus (`percent` = fraction x100). Fail-closed, jamais d'exception : erreur / 429 après 1 retry / timeout / JSON cassé / chaîne inconnue = `ok=False` + « donnée sécurité indisponible ». Choix prudents documentés en tête du fichier (RugCheck : holders dont `address`/`owner` = `markets[].pubkey` ou `markets[].liquidityA/BAccount.owner` (OBJETS, pas des chaînes) exclus, `markets` illisible = calcul brut ; autorité `null` = OK, clé absente = alerte ; `warn` -> `warnings`, ne bloque pas). |
| `notify.py` | Alertes téléphone via ntfy (gratuit, sans compte). Canal secret dans `.env` : `NTFY_TOPIC=...` (ou `--ntfy-topic`). Ne lève jamais d'exception, anti-doublon 60 s. Alertes : démarrage, entrée/sortie simulées, coupe-circuit, Chrome fermé, arrêt du bot, rapport du jour (`--report-hour`, défaut 21 h). Jamais de clé ni de donnée sensible dans un message. |
| `gardien.py` / `lancer_gardien.bat` / `installer_demarrage.bat` | Gardien : relance Chrome en mode debug (port 9222, profil `C:\chrome-debug`) et `pilot.py --auto` s'ils tombent (pause croissante, 6 relances/h max puis alerte ntfy et arrêt). Refuse `--live`. `installer_demarrage.bat` le lance à l'ouverture de session Windows (tâche `FomoGardien`). Le PC doit rester allumé : pour s'en passer, voir mode cloud. |
| `summary.py` / `resume.bat` | Résumé lisible en français de `pilot.log` + `state.json`. |
| `summary.py --cloud` / `resume_cloud.bat` | Résumé du bot cloud : lit sans clé `raw.githubusercontent.com/neoniterre/fomo-pilot/data/` (`state.json`, `trades.jsonl`, `STOP`), ~5 min de retard (cache GitHub). Réseau coupe / 404 / JSON cassé = message clair, jamais de plantage. |
| `.github/workflows/bot-cloud.yml` | **Bot PAPER dans le cloud, sans PC** : `pilot.py --auto --cloud` ~5 h 45 (`timeout 345m`), puis se relance tout seul (+ cron toutes les 6 h en filet). État (`state.json`, `history.json`, `trades.jsonl`) sauvegardé sur la branche **`data`** toutes les 15 min et repris au run suivant. **Arrêt d'urgence : créer un fichier `STOP` à la racine de la branche `data`** (ou désactiver le workflow dans l'onglet Actions). Secret GitHub `NTFY_TOPIC` pour les alertes. Ne doit JAMAIS contenir `--live` / `--auto-entry` (test `test_cloud_never_live_cli_and_workflows`). `cloud-test.yml` : essai court, sans relance. |
| `lancer_bot.bat` | Lance les tests puis le bot en paper (double-clic). |
| `test_*.py` | Tests sans réseau ni clé (`test_pilot.py` : reconnexion Chrome et garde-fou des clics avec un faux navigateur). Lancés aussi sur GitHub Actions à chaque push (`.github/workflows/tests.yml`). **Doivent passer avant chaque commit. Ne jamais supprimer un test.** |
| `requirements.txt` | Versions exactes des paquets du venv (`pip install -r requirements.txt`). |
| `history.json` | Relevés de prix / volume sauvegardés (la variation 30 min survit à un redémarrage, ignoré si > 90 min). Exclu de git. |

## Commandes (Windows, dans le dossier du projet)
```
.\venv\Scripts\python.exe test_risk.py
.\venv\Scripts\python.exe test_reader.py
.\venv\Scripts\python.exe test_scanner.py
.\venv\Scripts\python.exe test_pilot.py
.\venv\Scripts\python.exe test_notify.py
.\venv\Scripts\python.exe test_gardien.py
.\venv\Scripts\python.exe test_security.py
.\venv\Scripts\python.exe test_summary.py
.\venv\Scripts\python.exe test_positions.py
.\venv\Scripts\python.exe pilot.py --auto --navigate --model claude-haiku-5-5 --capital 20 --min-30m 20 --min-1h 50
.\venv\Scripts\python.exe pilot.py --auto --cloud --capital 20 --min-30m 20 --min-1h 50   # sans Chrome (python -m playwright install chromium)
# TEST glissade (comptes séparés obligatoires, sinon refus ; 30 $ mini : avec 20 $ la marge 8 % rend chaque trade < 1 $) :
.\venv\Scripts\python.exe pilot.py --auto --cloud --capital 30 --min-30m 20 --min-1h 50 --gap-buffer-pct 8 --exit-slippage-pct 1 --state-file state_test.json --trade-log trades_test.jsonl
.\venv\Scripts\python.exe summary.py --watch
.\venv\Scripts\python.exe summary.py --cloud            # bot cloud (ou double-clic resume_cloud.bat)
```
Clé API dans `.env` : `ANTHROPIC_API_KEY=...` (facturée à part du forfait Pro). Chrome doit tourner en mode debug
(`--remote-debugging-port=9222 --user-data-dir="C:\chrome-debug"`) et être connecté à fomo.

## Données réelles à connaître
- DexScreener : `/latest/dex/search?q=` et `/latest/dex/tokens/{adresse}`. Champs : `priceUsd` (string),
  `priceChange.m5/h1/h6/h24`, `volume.*`, `liquidity.usd`, `marketCap`, `pairCreatedAt` (ms). **Pas de variation 30 min.**
- **Stop qui glisse (CYBERLEEK, 18/11/2026)** : stop -12 % sorti à -20,1 %. Relevés de la branche `data` : -11,8 % de 04:45:17
  à 04:47:45 UTC puis -20,1 % au relevé suivant (37 s) et le prix est resté vers -19 % : **vrai trou de prix**, pas un artefact
  multi-pools (pool principal = 99 % de la liquidité). **DexScreener met à jour le prix environ toutes les 30 s** (mesuré le
  18/11 : changements à 28 s / 28 s / 63 s d'écart en relevant toutes les 5 s) : la boucle 5 s voit chaque nouveau prix en
  ≤ 5 s (avant : jusqu'à 36 s de retard), mais un trou entre deux mises à jour DexScreener (~30 s) reste possible.
- Les symboles ne sont pas uniques (faux « GTA6 » sur BSC avec +507 % et sans liquidité) -> toujours associer par prix et liquidité.
- RugCheck (`api.rugcheck.xyz`) : injoignable depuis le PC d'Elhadj le 17/11/2026 (certificat TLS non reconnu, ne PAS
  désactiver la vérification) -> en local, toutes les entrées Solana `--cloud` sont refusées. Joignable depuis GitHub Actions.
  Fixtures réelles : RugCheck BONK (`docs/fixture_rugcheck_bonk.json`, autorités `null`, pas de pool), pump_fun
  (`fixture_rugcheck_pool_pumpfun.json`, courbe = 82,67 %, top5 sans pool 7,36) et raydium_cpmm (`fixture_rugcheck_pool_raydium.json`,
  pool = 26,36 %, top5 sans pool 12,38), GoPlus USDT. 9 memecoins récents sur 14 ont leur pool au rang 1 (6 à 83 %).
- Fomo n'affiche pas le top 5 holders mais le top 10 : on l'utilise comme proxy sûr (top5 <= top10).
- **fomo.family/top-movers existe en 2 formats** : tableau (desktop : « Position in this view » une seule fois dans
  l'en-tête, puis chaque ligne commence par son rang seul après « Buy asset ») et cartes (« Position in this view: N »
  avant chaque token). `parse_fomo_list` doit lire LES DEUX. Test de non-régression : `test_parse_fomo_table`
  (17/11/2026 : une version sans le tableau lisait 0 token sur la vraie page, et c'est revenu 2 fois via des copies anciennes).

## Workflow git
- `git pull` avant de travailler, petits commits, message clair, `git push` sur `main`.
- Ne jamais forcer un push. En cas de conflit : s'arrêter et expliquer.
- Après une correction : lancer TOUS les `test_*.py` (risk, reader, scanner, pilot, notify, gardien, security, summary, positions), puis commiter.
- Les options de TEST (`--gap-buffer-pct`, `--exit-slippage-pct`) ne vont JAMAIS dans `bot-cloud.yml` sans accord d'Elhadj ;
  `pilot.py` refuse de les utiliser avec `state.json` / `trades.jsonl` (les vrais comptes papier).
  Avant de remplacer un fichier, `git diff` : un fichier écrit à partir d'une ancienne version efface les corrections. Garder `summary.py` aligné avec les lignes de log.

## État / à faire (priorité)
1. **Fiabilité** : FAIT (reconnexion si Chrome fermé, BTC 3 sources, `history.json`). Reste : délais fomo plus tolérants.
2. **Gardien + démarrage automatique** : FAIT (`gardien.py`), à valider sur le PC. Ne marche que PC allumé.
3. **Alertes téléphone** : FAIT (ntfy, `notify.py`). Telegram (pour répondre au bot) : plus tard, si besoin.
4. **Mode cloud** : FAIT (`security.py`, `--cloud`, `bot-cloud.yml` en continu sur GitHub Actions, état sur `data`,
   `summary.py --cloud`). Reste : **valider une entrée simulée complète dans le cloud** (scan -> RugCheck/GoPlus ->
   `risk.process` -> entrée paper -> sortie), aucune vue à ce jour (filtres momentum stricts).
5. Passage en live : **seulement** après plusieurs jours de paper concluants, décision d'Elhadj.
