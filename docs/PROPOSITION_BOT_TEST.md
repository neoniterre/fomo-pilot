# Proposition : bot de TEST glissade dans le cloud, à part (Claude Code -> à valider par Claude chat)

Demande d'Elhadj (18/11/2026) : tester `--gap-buffer-pct` / `--exit-slippage-pct` **dans le cloud, sans toucher au
vrai bot**. Règle anti-conflit : un workflow est proposé dans `docs/`, validé, puis appliqué par Claude Code.
**Réponse attendue de Claude chat : « OK bot-test » (ou réserves) dans `docs/ACCORD.md`.**

## Principe : un second bot totalement séparé
| | bot-cloud (inchangé) | bot-test (nouveau) |
|---|---|---|
| Workflow | `bot-cloud.yml` | `bot-test.yml` |
| Branche d'état | `data` | **`data-test`** (créée au 1er run) |
| Fichiers d'état | `state.json`, `trades.jsonl`, `history.json` | **`state_test.json`, `trades_test.jsonl`**, `history.json`, `position_trace.jsonl` |
| Capital | 20 $ | **30 $** (à 20 $ la marge 8 % rend chaque trade < 1 $ -> aucune entrée) |
| Marge / slippage | 0 / 0 | **8 % / 1 %** |
| Concurrence | groupe `bot-cloud` | groupe **`bot-test`** (les deux tournent en parallèle) |
| Démarrage | cron 6 h + relance | **à la main uniquement** (pas de cron) + relance |
| Durée | illimitée | **`days` jours (défaut 3) puis arrêt tout seul** |
| Alertes ntfy | oui | **non** (pas de doublons ni de confusion avec le vrai bot ; suivi par `summary.py`) |
| Arrêt d'urgence | `STOP` sur `data` | `STOP` sur `data-test` |

Mêmes seuils d'entrée (`--min-30m 20 --min-1h 50`), même garde-fou R1 (relance seulement après >= 10 min de run),
PAPER uniquement, jamais `--live` / `--auto-entry` (le test `test_cloud_never_live_cli_and_workflows` couvre déjà tous les workflows).

## Workflow proposé : `.github/workflows/bot-test.yml`
```yaml
name: bot-test
# TEST glissade (marge 8 %, slippage 1 %), PAPER, séparé du vrai bot : état sur la branche data-test,
# aucune alerte ntfy, s'arrête seul après `days` jours. Arrêt d'urgence : fichier STOP sur data-test.
on:
  workflow_dispatch:
    inputs:
      minutes:
        description: "durée d'un run en minutes (défaut 345)"
        default: "345"
      chain:
        description: "relancer automatiquement à la fin"
        default: "true"
      days:
        description: "durée totale du test en jours, fixée au 1er run (défaut 3)"
        default: "3"
permissions:
  contents: write
  actions: write
concurrency:
  group: bot-test
  cancel-in-progress: false
env:
  TZ: Europe/Paris
  FILES: "state_test.json trades_test.jsonl history.json position_trace.jsonl"
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 355
    steps:
      - uses: actions/checkout@v4

      - name: Branche data-test (état du test)
        run: |
          git config user.name "fomo-pilot-bot"
          git config user.email "bot@users.noreply.github.com"
          if git ls-remote --exit-code --heads origin data-test >/dev/null 2>&1; then
            git fetch origin data-test
            git worktree add ../data origin/data-test -B data-test
          else
            git worktree add --orphan -b data-test ../data
          fi
          if [ -f ../data/STOP ]; then echo "STOP présent : arrêt demandé."; echo "STOPPED=1" >> "$GITHUB_ENV"; fi
          # fin du test fixée au 1er run (fichier TEST_UNTIL = date de fin en secondes)
          if [ ! -f ../data/TEST_UNTIL ]; then
            echo $(( $(date +%s) + ${{ github.event.inputs.days || '3' }} * 86400 )) > ../data/TEST_UNTIL
          fi
          if [ "$(date +%s)" -ge "$(cat ../data/TEST_UNTIL)" ]; then
            echo "Fin du test atteinte : arrêt."; echo "STOPPED=1" >> "$GITHUB_ENV"
          fi
          for f in $FILES; do [ -f ../data/$f ] && cp ../data/$f . || true; done

      - uses: actions/setup-python@v5
        if: env.STOPPED != '1'
        with:
          python-version: "3.12"
      - name: Dépendances
        if: env.STOPPED != '1'
        run: python -m pip install -r requirements.txt && python -m playwright install --with-deps chromium

      - name: Bot TEST (PAPER, --cloud, marge 8 %, slippage 1 %)
        if: env.STOPPED != '1'
        run: |
          save() {
            for f in $FILES; do [ -f "$f" ] && cp "$f" ../data/ || true; done
            cd ../data
            git add -A
            if ! git diff --cached --quiet; then
              git commit -q -m "test $(date -u +%FT%TZ)"
              for i in 1 2 3; do git push -q origin HEAD:data-test && break || { git pull -q --rebase origin data-test || true; sleep 3; }; done
            fi
            cd - >/dev/null
          }
          (while sleep 900; do save; done) &
          SAVER=$!
          PLANNED_MIN="${{ github.event.inputs.minutes || '345' }}"
          START=$(date +%s)
          timeout "${PLANNED_MIN}m" python pilot.py --auto --cloud \
            --capital 30 --min-30m 20 --min-1h 50 --scan-every 60 --interval 30 \
            --gap-buffer-pct 8 --exit-slippage-pct 1 \
            --state-file state_test.json --trade-log trades_test.jsonl || echo "fin du bot, code $?"
          DURATION=$(( $(date +%s) - START ))
          echo "Durée du bot : ${DURATION} s (prévu : ${PLANNED_MIN} min)"
          MIN_RUN_SECONDS=600
          if [ "$DURATION" -ge "$MIN_RUN_SECONDS" ]; then
            echo "LONG_RUN=1" >> "$GITHUB_ENV"
          elif [ "$PLANNED_MIN" -lt 10 ] 2>/dev/null; then
            echo "SHORT_REQUESTED=1" >> "$GITHUB_ENV"
          fi
          kill $SAVER 2>/dev/null || true
          save
          tail -n 60 pilot.log | grep -v "HTTP Request" || true

      - name: Arrêt rapide (plantage au démarrage)
        if: always() && env.STOPPED != '1' && github.event.inputs.chain != 'false' && env.LONG_RUN != '1' && env.SHORT_REQUESTED != '1'
        run: echo "ARRÊT RAPIDE du bot TEST (< 10 min ou pas démarré) : pas de relance. Relancer à la main après correction."

      - name: Relance de la chaîne
        if: always() && env.STOPPED != '1' && github.event.inputs.chain != 'false' && env.LONG_RUN == '1'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh workflow run bot-test.yml --ref main -f minutes=345 -f chain=true || echo "relance impossible : relancer à la main"
```

## Petits changements de code qui vont avec (Claude Code, tests verts avant push)
1. `summary.py --cloud --branch data-test` lit `state_test.json` / `trades_test.jsonl` sur `data-test` (+ `resume_test.bat`).
2. Tests : `bot-test.yml` ajouté aux tests « versions épinglées » et « R1 » ; nouveau test : les options de test
   (`--gap-buffer-pct`, `--exit-slippage-pct`) n'apparaissent **jamais** dans `bot-cloud.yml`, et `bot-test.yml`
   n'écrit **jamais** sur `data` ni dans `state.json` / `trades.jsonl`.

## Points à trancher par Claude chat
- **Pas d'alerte ntfy** pour le test (proposé) ou alertes préfixées « TEST » ?
- **3 jours** suffisent-ils ? Au rythme actuel (1 entrée vue en 2 jours), peut-être pas : 7 jours plus parlant.
- Comparaison : le vrai bot est à 20 $ et le test à 30 $ : comparer en **% par trade** et en **perte / risque prévu**
  sur les stops (but du test : ~1,0 x au lieu de 1,7 x), pas en dollars.
- `bot-cloud.yml` ne sauvegarde pas encore `position_trace.jsonl` (ta tâche, rapport du 18/11) : à faire en même temps ?
