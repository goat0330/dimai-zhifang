@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Verify-DiMai.ps1"
if errorlevel 1 (
  echo 发现未通过的检查项，请查看上述原因。
  pause
  exit /b 1
)
pause
