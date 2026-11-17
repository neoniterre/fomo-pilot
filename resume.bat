@echo off
chcp 65001 >nul
cd /d "%~dp0"
venv\Scripts\python.exe summary.py --watch
echo.
echo Ferme (si erreur ci-dessus, copie-la).
pause
