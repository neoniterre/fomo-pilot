@echo off
chcp 65001 > NUL
cd /d "%~dp0"
echo === Gardien : relance Chrome et le bot tout seul (PAPER) ===
venv\Scripts\python.exe gardien.py
echo.
echo Le gardien s est arrete. Voir gardien.log et pilot.log.
pause
