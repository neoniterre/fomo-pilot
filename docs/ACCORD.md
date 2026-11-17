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
