# fomo-pilot

Bot de **paper trading** (simulation) de memecoins pour fomo.family. Propriétaire : Elhadj (France, parle français
décontracté, veut des réponses **courtes** et des corrections appliquées directement, sans longues explications).
Mots d'ordre : **efficacité, rapidité, prévoyance**.

## Règles absolues
- **Paper uniquement.** Ne jamais lancer ni activer `--live`, ne jamais exécuter de vrai trade, ne jamais cliquer
  Buy / Sell / Confirm / Swap / Withdraw / Transfer. `--auto` refuse déjà `--live`, ne pas lever ce garde-fou.
- **Ne jamais toucher au `.env`, ne jamais afficher ni commiter une clé API.** Ne jamais coller de clé dans un message.
- **Fail-closed** : un chiffre illisible ou manquant = `None` = entrée refusée par `risk.py`. Ne jamais estimer ni deviner.
- **Les desk rules vivent dans `risk.py`** (code), pas dans un prompt. Ne les assouplir que si Elhadj le demande
  explicitement (option CLI `--min-30m`, `--min-1h` pour les seuils de momentum).
- Les chiffres viennent du **code** (DexScreener), jamais du modèle. Le modèle ne fait que naviguer, lire le top
  holders et lister les alertes de la page.

## Architecture
| Fichier | Rôle |
|---|---|
| `risk.py` | Desk rules v4 : filtres d'entrée, taille de position (risque/stop), sorties (TP1/TP2/stop/trailing/volume), coupe-circuit -3 %/jour, max trades. État dans `state.json`. Garde-fous clics : `ui_gate` (texte du sélecteur) puis `element_gate` (texte RÉEL de l'élément, du bouton parent et du submit du formulaire, juste avant le clic). Ne jamais les affaiblir. |
| `scanner.py` | Listes publiques fomo (`parse_fomo_list`), client DexScreener, `resolve_token` (association symbole -> token par prix ±10 % et dominance de liquidité), métriques, `PriceHistory` (variation 30 min calculée par nos relevés), `VolumeTracker`, `save_history` / `load_history` (`history.json`). |
| `reader.py` | Lecture du texte de page par code, variation BTC 1h (Binance -> Kraken -> CoinGecko). |
| `pilot.py` | Boucle principale. Modes : texte (gratuit), `anthropic`/`xai` (modèle lit l'écran), `--auto` (scan -> filtres code -> vérif page -> entrée simulée). Si Chrome est fermé : surveille les positions via DexScreener et retente la connexion toutes les 30 s pendant `--reconnect-min` minutes (défaut 30), puis s'arrête. `--auto --cloud` : sans Chrome debug ni modèle ni clé Anthropic, listes fomo publiques en Chromium headless, holders/alertes via `security.py` ; refuse `--live`/`--auto-entry`, exige `--auto`, ignore `--navigate` (aucun clic), pas de reconnexion (Chromium arrêté = bot arrêté + alerte). |
| `security.py` | Mode cloud : `check_token(chain, address)` -> top5/top10 holders + `red_flags`. Solana = RugCheck, EVM (ethereum, bsc, base, arbitrum, polygon) = GoPlus (`percent` = fraction x100). Fail-closed, jamais d'exception : erreur / 429 après 1 retry / timeout / JSON cassé / chaîne inconnue = `ok=False` + « donnée sécurité indisponible ». Choix prudents documentés en tête du fichier (RugCheck : holders dont `address`/`owner` = `pubkey`/`liquidityAAccount`/`liquidityBAccount` d'un market exclus, `markets` illisible = calcul brut ; autorité `null` = OK, clé absente = alerte ; `warn` -> `warnings`, ne bloque pas). |
| `notify.py` | Alertes téléphone via ntfy (gratuit, sans compte). Canal secret dans `.env` : `NTFY_TOPIC=...` (ou `--ntfy-topic`). Ne lève jamais d'exception, anti-doublon 60 s. Alertes : démarrage, entrée/sortie simulées, coupe-circuit, Chrome fermé, arrêt du bot, rapport du jour (`--report-hour`, défaut 21 h). Jamais de clé ni de donnée sensible dans un message. |
| `gardien.py` / `lancer_gardien.bat` / `installer_demarrage.bat` | Gardien : relance Chrome en mode debug (port 9222, profil `C:\chrome-debug`) et `pilot.py --auto` s'ils tombent (pause croissante, 6 relances/h max puis alerte ntfy et arrêt). Refuse `--live`. `installer_demarrage.bat` le lance à l'ouverture de session Windows (tâche `FomoGardien`). Le PC doit rester allumé : pour s'en passer, voir mode cloud. |
| `summary.py` / `resume.bat` | Résumé lisible en français de `pilot.log` + `state.json`. |
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
.\venv\Scripts\python.exe pilot.py --auto --navigate --model claude-haiku-5-5 --capital 20 --min-30m 20 --min-1h 50
.\venv\Scripts\python.exe pilot.py --auto --cloud --capital 20 --min-30m 20 --min-1h 50   # sans Chrome (python -m playwright install chromium)
.\venv\Scripts\python.exe summary.py --watch
```
Clé API dans `.env` : `ANTHROPIC_API_KEY=...` (facturée à part du forfait Pro). Chrome doit tourner en mode debug
(`--remote-debugging-port=9222 --user-data-dir="C:\chrome-debug"`) et être connecté à fomo.

## Données réelles à connaître
- DexScreener : `/latest/dex/search?q=` et `/latest/dex/tokens/{adresse}`. Champs : `priceUsd` (string),
  `priceChange.m5/h1/h6/h24`, `volume.*`, `liquidity.usd`, `marketCap`, `pairCreatedAt` (ms). **Pas de variation 30 min.**
- Les symboles ne sont pas uniques (faux « GTA6 » sur BSC avec +507 % et sans liquidité) -> toujours associer par prix et liquidité.
- RugCheck (`api.rugcheck.xyz`) : injoignable depuis le PC d'Elhadj le 17/11/2026 (certificat TLS non reconnu, ne PAS
  désactiver la vérification) -> en local, toutes les entrées Solana `--cloud` sont refusées. Joignable depuis GitHub Actions.
  Fixtures réelles : RugCheck BONK (`docs/fixture_rugcheck_bonk.json`, autorités `null`), GoPlus USDT. Les pools dans le top
  holders (30-90 % sur un memecoin récent) sont testés avec une fixture synthétique (pas observés sur BONK).
- Fomo n'affiche pas le top 5 holders mais le top 10 : on l'utilise comme proxy sûr (top5 <= top10).
- **fomo.family/top-movers existe en 2 formats** : tableau (desktop : « Position in this view » une seule fois dans
  l'en-tête, puis chaque ligne commence par son rang seul après « Buy asset ») et cartes (« Position in this view: N »
  avant chaque token). `parse_fomo_list` doit lire LES DEUX. Test de non-régression : `test_parse_fomo_table`
  (17/11/2026 : une version sans le tableau lisait 0 token sur la vraie page, et c'est revenu 2 fois via des copies anciennes).

## Workflow git
- `git pull` avant de travailler, petits commits, message clair, `git push` sur `main`.
- Ne jamais forcer un push. En cas de conflit : s'arrêter et expliquer.
- Après une correction : lancer TOUS les `test_*.py` (risk, reader, scanner, pilot, notify, gardien, security), puis commiter.
  Avant de remplacer un fichier, `git diff` : un fichier écrit à partir d'une ancienne version efface les corrections. Garder `summary.py` aligné avec les lignes de log.

## État / à faire (priorité)
1. **Fiabilité** : FAIT (reconnexion si Chrome fermé, BTC 3 sources, `history.json`). Reste : délais fomo plus tolérants.
2. **Gardien + démarrage automatique** : FAIT (`gardien.py`), à valider sur le PC. Ne marche que PC allumé.
3. **Alertes téléphone** : FAIT (ntfy, `notify.py`). Telegram (pour répondre au bot) : plus tard, si besoin.
4. **Mode cloud** (sans PC) : `security.py` + `--cloud` FAIT (spec : `docs/SPEC_CLOUD.md`). Reste : vérifier RugCheck et
   Chromium headless sur GitHub Actions, exécution planifiée, stockage de l'état.
5. Passage en live : **seulement** après plusieurs jours de paper concluants, décision d'Elhadj.
