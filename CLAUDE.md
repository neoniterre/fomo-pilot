# fomo-pilot : règles pour Claude

Bot de trading sur fomo.family. Le modèle observe et propose, `risk.py` (code pur) décide.
Ce dossier est la **seule source de vérité** : on modifie les fichiers ici, directement.
Ne jamais repartir d'une copie venue d'ailleurs (Téléchargements, zip, autre conversation)
sans la comparer d'abord à la version présente ici.

## Sécurité (non négociable)
- Ne jamais lire, afficher, copier ni modifier le contenu de `.env`. Pour vérifier une clé,
  n'afficher que des booléens (présente / préfixe correct), jamais un nom ou une valeur lus du fichier.
- Mode papier par défaut. Ne jamais lancer avec `--live` ou `--auto-entry`.
- Ne jamais affaiblir `ui_gate` / `FORBIDDEN` / `TRADE_WORDS` dans `risk.py`.

## Avant et après chaque changement
- Lancer les trois fichiers de tests avec le venv :
  `.\venv\Scripts\python.exe test_risk.py`, `test_reader.py`, `test_scanner.py`.
- Un changement n'est fini que si tous passent.
- Ne jamais supprimer un test existant pour faire passer une nouvelle version :
  chaque test protège une correction déjà faite.

## Git
- Le dossier est un dépôt git (branche `main`). Après chaque changement dont les tests
  passent : un commit avec un message clair en français, puis `git push` vers
  GitHub (`origin` = github.com/neoniterre/fomo-pilot, privé). Ne jamais `push --force`
  sans accord explicite de l'utilisateur.
- Avant de remplacer un fichier, regarder `git diff` pour voir ce qui serait perdu.
- `.env`, `venv/`, logs et `state.json` sont exclus par `.gitignore` : ne jamais les ajouter.

## Corrections à ne pas perdre (tests de non-régression)
- `scanner.parse_fomo_list` doit lire les DEUX formats de fomo.family/top-movers :
  le tableau actuel (rang seul sur sa ligne, après « Buy asset ») et l'ancien format à
  blocs « Position in this view: N ». Test : `test_parse_fomo_table` (17/11/2026 : l'ancien
  parseur seul lisait 0 token sur la vraie page).

## Lancer le bot
- Chrome de débogage : `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chrome-debug"`
- Auto papier : `.\venv\Scripts\python.exe pilot.py --auto --navigate --model claude-haiku-5-5 --capital 20`

## Journal des changements
Ajouter une ligne datée ici à chaque modification du code.
- 2026-11-17 : scanner lit le tableau top-movers + test `test_parse_fomo_table`.
