@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Verify-BusinessFlow.ps1"
if errorlevel 1 (
  echo 协同处置验收未通过，请查看上方失败步骤。
  pause
  exit /b 1
)
pause
