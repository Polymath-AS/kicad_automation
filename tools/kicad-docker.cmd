@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0kicad-docker.ps1" %*
exit /b %ERRORLEVEL%
