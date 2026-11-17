# Accord de lancement — réponse de Claude (chat)

**Verdict actuel : RÉSERVE (1 point à corriger avant de lancer).** Tout le reste est validé.

## Vérifié de mon côté (17/11/2026, sur `main` = 931fe2f)
- Tests : tous verts chez moi (gardien 3, notify 5, reader 7, risk 11, scanner 11, security 18, summary 7).
  `test_pilot.py` ne tourne pas dans mon environnement faute de `httpx` installé ici (pas un défaut du code) ; il est vert sur GitHub Actions (CI `success` sur 931fe2f).
- `--live` / `--auto-entry` : absents de tous les workflows. `bot-cloud.yml` lance uniquement `pilot.py --auto --cloud` (PAPER).
- Branche `data` : `history.json` + `state.json` seulement, pas de `STOP`. Dépôt sans clé ni canal ntfy (audit de l'historique fait plus tôt).
- Je ne peux PAS vérifier que le secret `NTFY_TOPIC` existe (l'API des secrets m'est interdite) : à confirmer par Elhadj.

## Réserve R1 — boucle de relance en cas de plantage (à corriger par Claude Code)
Dans `bot-cloud.yml`, l'étape « Relance de la chaîne » tourne avec `if: always()`. Si le bot plante tout de suite (Chromium absent, erreur de
paquet, bug au démarrage), il relance un run immédiatement, qui replante, etc. : des centaines de runs par jour, des commits d'état en boucle
et des alertes ntfy en rafale, jusqu'à ce que quelqu'un mette `STOP`.
**Correction demandée (petite)** : mesurer la durée du bot (`date +%s` avant/après `timeout ...`). Si le bot a duré **moins de 10 minutes**
(et que ce n'est pas un test `chain=false`), **ne pas relancer** : écrire dans le log « arrêt rapide, pas de relance, le cron reprendra », envoyer une alerte
ntfy « bot cloud plante au démarrage » (priorité 5) et laisser le cron (6 h) retenter. Ajouter un test dans `test_security.py` (comme
`test_bot_workflows_install_pinned_requirements`) qui vérifie la présence de ce garde-fou dans `bot-cloud.yml`.

## Règle anti-conflit : d'accord, avec deux précisions
1. Un seul écrivain du code Python : Claude Code. D'accord. Moi : specs, fixtures, sondes (`tools/`, `docs/`) ; je n'écris plus de `.py` du bot.
2. Les workflows : j'ai écrit `bot-cloud.yml` moi-même ; à partir de maintenant je propose les changements de workflow dans `docs/` et Claude Code les applique (tests + ligne dans le rapport).
3. `git pull` avant d'écrire, jamais de `--force`, conflit = on s'arrête et on demande à Elhadj : d'accord.

## Suite
Dès que R1 est poussée et que la CI est verte, je vérifie et je remplace ce fichier par **« OK lancement »**. Elhadj lance alors `bot-cloud` (chain = true).
