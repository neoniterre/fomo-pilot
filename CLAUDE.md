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
| `risk.py` | Desk rules v4 : filtres d'entrée, taille de position (risque/stop), sorties (TP1/TP2/stop/trailing/volume), coupe-circuit -3 %/jour, max trades. État dans `state.json`. |
| `scanner.py` | Listes publiques fomo (`parse_fomo_list`), client DexScreener, `resolve_token` (association symbole -> token par prix ±10 % et dominance de liquidité), métriques, `PriceHistory` (variation 30 min calculée par nos relevés), `VolumeTracker`. |
| `reader.py` | Lecture du texte de page par code, variation BTC 1h (Binance -> Kraken -> CoinGecko). |
| `pilot.py` | Boucle principale. Modes : texte (gratuit), `anthropic`/`xai` (modèle lit l'écran), `--auto` (scan -> filtres code -> vérif page -> entrée simulée). |
| `summary.py` / `resume.bat` | Résumé lisible en français de `pilot.log` + `state.json`. |
| `lancer_bot.bat` | Lance les tests puis le bot en paper (double-clic). |
| `test_*.py` | Tests sans réseau ni clé. **Doivent passer avant chaque commit.** |

## Commandes (Windows, dans le dossier du projet)
```
.\venv\Scripts\python.exe test_risk.py
.\venv\Scripts\python.exe test_reader.py
.\venv\Scripts\python.exe test_scanner.py
.\venv\Scripts\python.exe pilot.py --auto --navigate --model claude-haiku-5-5 --capital 20 --min-30m 20 --min-1h 50
.\venv\Scripts\python.exe summary.py --watch
```
Clé API dans `.env` : `ANTHROPIC_API_KEY=...` (facturée à part du forfait Pro). Chrome doit tourner en mode debug
(`--remote-debugging-port=9222 --user-data-dir="C:\chrome-debug"`) et être connecté à fomo.

## Données réelles à connaître
- DexScreener : `/latest/dex/search?q=` et `/latest/dex/tokens/{adresse}`. Champs : `priceUsd` (string),
  `priceChange.m5/h1/h6/h24`, `volume.*`, `liquidity.usd`, `marketCap`, `pairCreatedAt` (ms). **Pas de variation 30 min.**
- Les symboles ne sont pas uniques (faux « GTA6 » sur BSC avec +507 % et sans liquidité) -> toujours associer par prix et liquidité.
- Fomo n'affiche pas le top 5 holders mais le top 10 : on l'utilise comme proxy sûr (top5 <= top10).

## Workflow git
- `git pull` avant de travailler, petits commits, message clair, `git push` sur `main`.
- Ne jamais forcer un push. En cas de conflit : s'arrêter et expliquer.
- Après une correction : lancer les 3 tests, puis commiter. Garder `summary.py` aligné avec les lignes de log.

## État / à faire (priorité)
1. **Fiabilité** : FAIT (reconnexion si Chrome fermé, BTC 3 sources, `history.json`). Reste : délais fomo plus tolérants.
2. **Gardien + démarrage automatique** (relance du bot et de Chrome debug, planificateur Windows).
3. **Alertes téléphone** (ntfy ou Telegram) + rapport de fin de journée.
4. **Mode cloud** (sans PC) : top holders / alertes via API de sécurité (RugCheck pour Solana, GoPlus pour EVM), exécution
   planifiée (GitHub Actions pour tester, puis petit serveur). Vérifier les conditions gratuites de ces API.
5. Passage en live : **seulement** après plusieurs jours de paper concluants, décision d'Elhadj.
