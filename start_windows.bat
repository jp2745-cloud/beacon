@echo off
REM Beacon on Windows (development mode: Bonsai is real, speech is a stand-in for Argmax).
REM 1) Start Bonsai first:  in the Bonsai-demo folder run  .\scripts\start_llama_server.ps1
REM 2) Then double-click this file.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 server.py %*) else (python server.py %*)
pause
