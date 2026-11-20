@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Resume du bot de TEST reentree (GitHub, branche data-test2). Rafraichi toutes les 60 s, Ctrl+C pour quitter.
venv\Scripts\python.exe summary.py --cloud --branch data-test2 --watch
echo.
echo Ferme (si erreur ci-dessus, copie-la).
pause
