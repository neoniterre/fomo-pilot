# Accord de lancement — réponse de Claude (chat)

**OK lancement**

Vérifié le 17/11/2026 sur `main` = `2c304e6` (R1 corrigée par `adb096e`) :
- R1 : le workflow ne relance que si le bot a tourné >= 10 min ; sinon alerte ntfy priorité 5 et le cron (6 h) retente. Logique relue étape par étape (YAML valide, `LONG_RUN` / `SHORT_REQUESTED` cohérents, un échec d'installation est couvert par `always()`).
- Tests verts chez moi (gardien 3, notify 5, reader 7, risk 11, scanner 11, security 19, summary 7) et CI GitHub verte sur `2c304e6`.
- Aucun `--live` / `--auto-entry` dans les workflows. PAPER uniquement.
- Règle anti-conflit : d'accord (un seul écrivain du code Python = Claude Code ; Claude chat = specs, fixtures, sondes ; `git pull` avant d'écrire ; pas de `--force`).

Conditions côté Elhadj avant de lancer :
1. Le secret GitHub `NTFY_TOPIC` doit exister (je ne peux pas le vérifier).
2. Ne pas faire tourner le bot sur le PC en même temps (deux comptes simulés, alertes en double).
3. Lancer : onglet Actions -> bot-cloud -> Run workflow, `minutes` = 345, `chain` = true. Arrêt d'urgence : fichier `STOP` à la racine de la branche `data`.

Risque résiduel connu (faible) : un bot qui planterait toujours après plus de 10 min relancerait des runs d'environ 10 min en boucle ; l'alerte « BOT ARRETE » préviendrait Elhadj, qui peut mettre `STOP`.

---

# Accord bot-test (glissade) — réponse de Claude (chat), 18/11/2026

**OK bot-test** (avec 1 réserve à appliquer en même temps)

Relu `docs/PROPOSITION_BOT_TEST.md` (main = `7438b8b`) contre `bot-cloud.yml` : même structure (worktree, `save()` toutes les 15 min, garde R1), états séparés (`data-test`, `state_test.json`, `trades_test.jsonl`), concurrence `bot-test` distincte, pas de cron, pas de secret ntfy passé au job, PAPER uniquement. Options `--gap-buffer-pct`, `--exit-slippage-pct`, `--trade-log`, `--state-file` présentes dans `pilot.py`.

## Les 4 points
1. **Alertes ntfy : aucune** (comme proposé). Pas de doublons avec le vrai bot ; suivi par `summary.py --cloud --branch data-test`.
2. **7 jours** (`days=7` au lancement). Au rythme actuel (1 entrée en 2 jours), 3 jours ne donneront probablement aucun stop à mesurer. Limite à garder en tête : même à 7 jours il peut n'y avoir qu'un ou deux stops, donc c'est un indice, pas une preuve.
3. **Comparaison en % et en ratio**, pas en dollars : pour chaque stop, `perte réelle / risque prévu` (cible ~1,0 x, contre 1,7 x pour CYBERLEEK). Ajouter dans `summary.py --branch data-test` ce ratio par stop, et le prix de sortie vs le prix du stop.
4. **Oui, sauvegarder `position_trace.jsonl` dans `bot-cloud.yml` en même temps** (ajouter le fichier aux deux listes `for f in ...` : copie au démarrage et `save()`), et idem côté `bot-test.yml` (déjà dans `FILES`).

## Réserve (à traiter avant de lancer)
- **`position_trace.jsonl` n'a aucune limite de taille.** À 1 ligne / 5 s / position (~17 000 lignes par jour et par position) et un push toutes les 15 min sur une branche publique, le fichier et l'historique git grossissent sans fin. Demande : plafonner (par ex. garder seulement les ~20 000 dernières lignes, ou ne tracer que les positions ouvertes + 1 h après la sortie) dans le code, avec un test. Sans ça, risque de branche `data` lourde.

## Conditions de lancement
- Claude Code applique `bot-test.yml` + `summary.py --branch` + les tests demandés (`bot-test.yml` n'écrit jamais sur `data` ; `bot-cloud.yml` ne contient jamais les options de test), tous les tests verts, CI verte, puis écrit « prêt » dans son rapport.
- Je revérifie (YAML, tests, CI) puis Elhadj lance : Actions -> bot-test -> Run workflow, `minutes` = 345, `chain` = true, `days` = 7. Arrêt d'urgence : fichier `STOP` sur la branche `data-test`.
- Le vrai bot (`bot-cloud`) continue de tourner pendant ce temps, inchangé en comportement.


---

# Vérification bot-test (main = `2034bc6`) — Claude (chat), 18/11/2026

**PAS ENCORE OK : 1 blocage, correction d'une ligne.**

**Blocage** : `.github/workflows/bot-test.yml` est un **YAML invalide** (ligne 95, colonne 71 : `mapping values are not allowed here`).
GitHub l'a déjà rejeté : les runs « bot-test.yml » des pushs `e90b604`..`2034bc6` sont en échec à 0 s
(« This run likely failed because of a workflow file issue »). Le workflow n'apparaîtrait donc pas dans Actions -> Run workflow.
Cause : l'étape « Arrêt rapide » a `run: echo "... (< 10 min ou pas démarré) : pas de relance. ..."` : le `: ` dans un scalaire simple casse le YAML.
**Correction** : passer cette ligne en bloc : `run: |` puis la commande `echo "..."` sur la ligne suivante, indentée.

**Test manquant** (la CI verte ne l'a pas vu) : ajouter à `test_*.py` un test qui charge CHAQUE `.github/workflows/*.yml` avec `yaml.safe_load`
(`pyyaml` dans `requirements.txt` si besoin, version épinglée) et échoue si un fichier est invalide.
Moi, avec `yaml.safe_load` : `bot-cloud`, `cloud-test`, `tests`, `probe*` sont valides ; seul `bot-test.yml` est cassé.

**Reste vérifié, OK** : 8 fichiers de tests verts chez moi (security, risk, reader, scanner, notify, gardien, summary, positions) ; `bot-cloud.yml` sauvegarde bien
`position_trace.jsonl` (reprise + `save()`) sans option de test ni autre changement ; `bot-test.yml` ne touche que `data-test`, `state_test.json`, `trades_test.jsonl`,
7 jours par défaut, pas de ntfy, pas de cron, R1 identique. Le vrai bot (`bot-cloud`) tourne (run en cours depuis 14:41, Paris).

Dès que la correction est poussée et que `bot-test` apparaît dans Actions : j'écris « OK bot-test » et Elhadj lance.

---

# OK bot-test — Claude (chat), 18/11/2026

**OK bot-test**

Revérifié sur `main` = `c7b46ea` : seule modification de `bot-test.yml` depuis `2034bc6` = l'étape « Arrêt rapide » en `run: |` (le reste identique) ;
`bot-cloud.yml` inchangé. Les 7 workflows se chargent avec `yaml.safe_load`. 9 fichiers de tests verts chez moi, CI verte sur `b57a448`, `bot-test` est `active` dans Actions.
Le vrai bot (`bot-cloud`) tourne toujours (run en cours).

**Lancement (Elhadj)** : Actions -> bot-test -> Run workflow, `minutes` = 345, `chain` = true, `days` = 7. Suivi : `resume_test.bat`. Arrêt d'urgence : fichier `STOP` sur `data-test`.
Claude Code : rien d'autre à faire sur ce sujet.

---

# OK bot-test2 — Claude (chat), 20/11/2026

**OK bot-test2**

Vérifié sur `main` = `03c4988` :
- `bot-cloud.yml` et `bot-test.yml` **inchangés** (diff vide depuis `915cc59`) ; aucune des 4 options de réentrée n'y figure.
- `bot-test2.yml` = `bot-test.yml` avec exactement les changements prévus (nom, `data-test2`, groupe `bot-test2`, fichiers `*_test2`, capital 20, sans marge ni slippage, 4 options + `--refusal-log`, relance de lui-même). Pas de ntfy, pas de `--live`, pas d'écriture sur `data` / `data-test`.
- Les 8 workflows se chargent avec `yaml.safe_load`. 10 fichiers de tests verts chez moi (109 tests dont 17 de réentrée), CI verte sur `4a91d23` et `03c4988`, `bot-test2` `active`.
- Tes 5 précisions sont acceptées : refus mesuré seulement si la réentrée est la seule cause ; règles appliquées à la décision finale ; volume absent = pas de blocage (donc la règle 4 agit surtout sur les rachats, comme CYBERLEEK 20:13) ; sortie volume / pnl 0 = sortie à perte ; relevé +30/+60 trop en retard = `missed`.

**Lancement** : sur ordre d'Elhadj (Actions -> bot-test2 -> Run workflow, `minutes` = 345, `chain` = true, `days` = 7). Arrêt d'urgence : fichier `STOP` sur `data-test2`.
Claude Code : rien d'autre à faire sur ce sujet.
