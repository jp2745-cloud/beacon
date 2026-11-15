@echo off
REM Beacon one-click start for Windows.
REM Opens Bonsai in its own window, then starts Beacon here and opens the browser.
REM Folder paths: change the two lines below if you installed somewhere else.
set BONSAI_DIR=C:\hackathon\Bonsai-demo
set BEACON_DIR=C:\hackathon\beacon
set MODEL=4B

title Beacon
echo Starting Bonsai in a second window (leave it open)...
start "Bonsai 2 %MODEL% - leave this window open" powershell -NoExit -ExecutionPolicy Bypass -Command "$env:BONSAI_MODEL='%MODEL%'; $env:BONSAI_THINKING='0'; Set-Location '%BONSAI_DIR%'; .\scripts\start_llama_server.ps1"

cd /d "%BEACON_DIR%"
echo.
echo Starting Beacon. The browser opens by itself.
echo Wait until the middle pill says "Bonsai 2 %MODEL% on this laptop" before you talk to it.
echo Close this window to stop Beacon.
echo.
python server.py
pause
