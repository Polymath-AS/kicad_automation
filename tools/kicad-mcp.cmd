@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0kicad-mcp.ps1" %*
exit /b %ERRORLEVEL%
