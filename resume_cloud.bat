@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Resume du bot cloud (GitHub, branche data). Rafraichi toutes les 60 s, Ctrl+C pour quitter.
venv\Scripts\python.exe summary.py --cloud --watch
echo.
echo Ferme (si erreur ci-dessus, copie-la).
pause
