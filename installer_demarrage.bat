@echo off
chcp 65001 > NUL
cd /d "%~dp0"
echo Installation du demarrage automatique du gardien a l ouverture de session Windows...
schtasks /create /tn "FomoGardien" /tr "\"%~dp0lancer_gardien.bat\"" /sc onlogon /rl limited /f
echo.
echo Pour retirer : schtasks /delete /tn "FomoGardien" /f
pause
