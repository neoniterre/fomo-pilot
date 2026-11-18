# Enquête : le stop -12 % est sorti à -20,1 % (CYBERLEEK, 18/11/2026) — à traiter par Claude Code

## Les faits (branche `data`, `trades.jsonl`, bot cloud PAPER)
- Achat 04:30:39 UTC : 1,33 $, prix théorique 0,0029078, `stop_pct` 12.
- Vente 04:48:21 UTC (17 min 42 s plus tard) : prix 0,0023223, raison `stop-loss (-20.1%)`, pnl **-0,2678 $**.
- Risque prévu : 1,33 x 12 % = 0,16 $ (0,8 % du capital). Perte réelle : 0,2678 $ = **1,7 x** le risque prévu. En réel ce serait pire (pas de slippage simulé).
- Cadence du bot cloud : un cycle ~ toutes les 36 s (interval 30 s + scan) ; `watch_positions()` est appelé à chaque cycle.

## Ce qu'on ne sait pas encore (et pourquoi : rien n'est tracé)
Le journal GitHub Actions n'affiche que la fin de `pilot.log` et `trades.jsonl` ne garde que l'achat et la vente. On ne voit pas le prix entre les deux.
Deux explications possibles, à départager avec des traces :
1. **Gap réel** : le prix a chuté de plus de 8 points entre deux relevés (36 s) — plausible sur un micro-cap.
2. **Prix artificiel** : `metrics_from_group` calcule un prix **moyenné par la liquidité sur tous les pools** du token. Si un pool apparaît, disparaît
   ou a un prix périmé, la moyenne peut sauter sans que le "vrai" prix bouge. `watch_positions` prend aussi `max(groups, key=liq)`.
   Autre piste : relevés manqués (`WARNING ... price unavailable this cycle, exits not evaluated`).

## À faire (ordre)
1. **Tracer** : pendant qu'une position est ouverte, écrire une ligne par cycle dans `position_trace.jsonl` : `ts`, `token`, `price`, `change_vs_entry_pct`,
   nombre de pools, liquidité totale, prix du pool principal seul, et un booléen « relevé manqué ». Sans réseau ni clé, ne bloque jamais le bot.
   (Je modifierai `bot-cloud.yml` pour sauvegarder ce fichier sur `data` : dis-moi simplement le nom final du fichier dans ton rapport.)
2. **Test sans réseau** qui rejoue une série de prix factice : chute de 0 à -25 % sur 3 relevés ; vérifier que la sortie se fait au 1er relevé <= -12 % et
   que `reason` et `pnl` sont corrects. Ajouter un cas « pool qui disparaît » : le prix moyenné saute de 15 % alors que le pool principal ne bouge pas ;
   le test doit montrer ce qu'il se passe aujourd'hui.
3. **Corriger si l'hypothèse 2 est confirmée** : pour les STOPS, utiliser le prix du pool principal (le plus liquide) et non la moyenne multi-pools, ou exiger
   2 relevés consécutifs sous le stop quand le nombre de pools change entre deux relevés. Choisir l'option la plus prudente pour le capital.
4. **Relevés plus fréquents** quand une position est ouverte : un cycle court dédié aux positions (toutes les ~10 s) séparé du scan (limite DexScreener : 300 req/min, large marge).
5. Option (à valider par Elhadj, ne pas activer par défaut) : simuler un slippage pessimiste à la sortie (ex. -1 %) pour que le paper ne soit pas trop optimiste.

## Règles
Paper uniquement. Tous les tests verts avant de commiter, une ligne dans `docs/RAPPORT_CLAUDE_CODE.md`, `git pull` avant d'écrire. Le bot cloud tourne en ce moment : tout changement de
`pilot.py` / `risk.py` / `scanner.py` passe par les tests verts, le run suivant prendra la nouvelle version.
