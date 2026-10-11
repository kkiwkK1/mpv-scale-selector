@echo off
rem scale-selector one-click installer entry (double-click to run).
rem This .bat lives in tools\ ; cd to the repository root first,
rem then run tools\install.ps1 and pause so the result stays visible.
rem NOTE: keep this file ASCII without BOM (cmd cannot handle a UTF-8 BOM).

cd /d "%~dp0.." || (echo ERROR: cannot cd to repo root & pause & exit /b 1)
if not exist "tools\install.ps1" (echo ERROR: tools\install.ps1 not found & pause & exit /b 1)

powershell -NoProfile -ExecutionPolicy Bypass -File "tools\install.ps1"
set "EXITCODE=%ERRORLEVEL%"

echo.
echo installer finished, exit code = %EXITCODE%
echo 0=OK  1=param/env/IO error  2=precheck blocked (source problem)  3=not installed  4=inconsistent
pause
exit /b %EXITCODE%
