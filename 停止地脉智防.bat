@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-DiMai.ps1"
if errorlevel 1 (
  echo 停止服务失败，请检查 Docker Desktop。
  pause
  exit /b 1
)
pause
