# Spec : règles de réentrée (TEST uniquement) — Claude chat -> Claude Code, 20/11/2026

Demande d'Elhadj : tester dans un bot de test (jamais dans le vrai bot) des règles contre les rachats répétés d'un token qui tombe.
Faits (branche `data`, 18-20/11) : CYBERLEEK racheté 3 fois en 1 h 30 (stop -13,2 %, sortie volume 0 $ dans la MÊME minute que l'achat, stop -12,0 %) = que des pertes.
FLOAT : TP1+TP2+trailing (+0,77 $), racheté, stoppé -12,4 % en 3 min, racheté à 21:41 : déjà ~+30 % au plus haut. **Un simple délai raterait ce genre de rebond** :
les règles ci-dessous sont donc CONDITIONNELLES et on mesure ce qu'elles coûtent (point 5). 9 entrées en 3 jours : trop peu pour trancher à l'intuition.

## Principe : un 3e bot de test, séparé, avec UNIQUEMENT ces options
Pourquoi pas dans `bot-test` : il teste déjà la glissade (marge 8 % + slippage 1 %) ; y ajouter les règles mélangerait deux expériences.
Le nouveau bot a **les mêmes réglages que le vrai bot** (capital 20 $, pas de marge, pas de slippage) + les options ci-dessous : la comparaison avec `bot-cloud` est directe (mêmes signaux, mêmes tailles).
- `.github/workflows/bot-test2.yml` : copie exacte de `bot-test.yml` (déjà validé, garde R1, `days` = 7, pas de ntfy, pas de cron), avec : branche **`data-test2`**, groupe de concurrence `bot-test2`,
  fichiers `state_test2.json`, `trades_test2.jsonl`, `refusals_test2.jsonl`, `history.json`, `position_trace.jsonl`, `--capital 20`, **sans** `--gap-buffer-pct` ni `--exit-slippage-pct`, avec les 4 options ci-dessous.
  Pré-validé par moi (copie de `bot-test.yml` avec ces seuls changements) : tu peux l'appliquer directement, je revérifie après. **Ne pas modifier `bot-test.yml` ni `bot-cloud.yml`** (`bot-test` tourne jusqu'au 25/11).
- Options **désactivées par défaut** (0 / off = comportement historique). Refus de démarrer si activées avec `state.json` / `trades.jsonl` (comme les autres options de test). Jamais dans `bot-cloud.yml` ni `bot-test.yml` (nouveau test).

## Les règles (`risk.py` / `pilot.py`)
1. **Cooldown** `--reentry-cooldown-min 20` : après une sortie à perte ou nulle sur un token (stop-loss, sortie volume, pnl <= 0), pas de nouvelle entrée sur ce token pendant 20 min.
   (Une sortie gagnante TP / trailing ne déclenche pas de cooldown.)
2. **Reprise de tendance** `--reentry-reclaim` : le cooldown passé, on ne rachète que si le prix actuel est >= le prix d'entrée de la position précédente ET que la chute de volume 1 h est < 30 %. Sinon refus (raison « réentrée : pas de reprise »).
3. **Plafond par token** `--max-stops-per-token-day 2` : après 2 stops-loss sur le même token le même jour (jour de Paris, comme le coupe-circuit), plus d'entrée sur ce token jusqu'au lendemain.
4. **Pas d'entrée sur volume qui chute** `--no-entry-volume-drop-pct 60` : refuser l'entrée si la règle de sortie « volume » se déclencherait au 1er relevé (cas CYBERLEEK 20:13 : achat et vente dans la minute, 0 $).
   Si la donnée de volume est indisponible : garder le comportement actuel (ne pas bloquer toutes les entrées), mais le dire dans le rapport.
- L'historique par token (dernière sortie, prix d'entrée précédent, nb de stops du jour) est dans l'état (`state_test2.json`), **rétro-compatible** : un `state.json` existant sans ces champs se charge comme avant.
- Chaque refus : une ligne `pilot.log` claire + une ligne dans `refusals_test2.jsonl` (`ts, token, règle, prix`). Ne bloque jamais le bot.

## 5. Mesurer ce que les refus coûtent (la vraie question : « et si la courbe remonte ? »)
Pour chaque refus, relever le prix du token à +30 min et +60 min (un appel DexScreener, par la boucle existante, sans bloquer) et l'écrire dans `refusals_test2.jsonl` (`price_30m`, `price_60m`, `change_pct` vs prix au refus).
`summary.py --cloud --branch data-test2` affiche : entrées, stops, pnl, **refus par règle, et pour les refus : combien auraient monté / baissé après 60 min**. C'est ça qui dira si une règle sauve de l'argent ou rate des rebonds.

## Tests (sans réseau, à ajouter)
- cooldown (stop puis tentative à +5 min refusée, à +21 min autorisée si reprise) ; sortie gagnante = pas de cooldown ;
- reprise de tendance : prix < ancien prix d'entrée refusé, >= accepté ; volume en chute refusé ;
- plafond 2 stops/jour/token, remise à zéro au changement de jour ;
- entrée sur volume qui chute refusée ; donnée de volume absente = comportement historique ;
- toutes options à 0 : résultats identiques à aujourd'hui (rejouer un scénario existant) ;
- `bot-cloud.yml` et `bot-test.yml` ne contiennent aucune de ces options ; `bot-test2.yml` n'écrit jamais sur `data` / `data-test` ni dans `state.json` / `trades.jsonl` ; `yaml.safe_load` OK.

## Règles
PAPER uniquement. `git pull` avant d'écrire, tous les `test_*.py` verts, CI verte, rapport en haut de `docs/RAPPORT_CLAUDE_CODE.md` avec « prêt », puis attendre ma réponse dans `docs/ACCORD.md` (30 min max, `git pull` toutes les 2 min).
Ne pas toucher aux branches `data*`, aux secrets, ni au `.env`. Le lancement de `bot-test2` se fait par Elhadj (ou moi sur son ordre) après mon OK.
