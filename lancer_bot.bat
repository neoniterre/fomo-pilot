@echo off
chcp 65001 > NUL
cd /d "%~dp0"
echo === Tests ===
venv\Scripts\python.exe test_risk.py || (echo ECHEC test_risk & pause & exit /b 1)
venv\Scripts\python.exe test_reader.py || (echo ECHEC test_reader & pause & exit /b 1)
venv\Scripts\python.exe test_scanner.py || (echo ECHEC test_scanner & pause & exit /b 1)
venv\Scripts\python.exe test_pilot.py || (echo ECHEC test_pilot & pause & exit /b 1)
venv\Scripts\python.exe test_notify.py || (echo ECHEC test_notify & pause & exit /b 1)
venv\Scripts\python.exe test_gardien.py || (echo ECHEC test_gardien & pause & exit /b 1)
venv\Scripts\python.exe test_security.py || (echo ECHEC test_security & pause & exit /b 1)
venv\Scripts\python.exe test_summary.py || (echo ECHEC test_summary & pause & exit /b 1)
echo Tests OK.
echo.
echo === Lancement du bot (PAPER, seuils 30min=20 et 1h=50) ===
echo Chrome doit etre ouvert en mode debug. Ctrl+C pour arreter.
echo.
venv\Scripts\python.exe pilot.py --auto --navigate --model claude-haiku-5-5 --capital 20 --min-30m 20 --min-1h 50
echo.
echo Le bot s est arrete. Si une erreur est affichee ci-dessus, copie-la.
pause
