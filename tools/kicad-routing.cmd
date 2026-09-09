@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0kicad-routing.ps1" %*
exit /b %ERRORLEVEL%
