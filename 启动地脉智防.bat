@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-DiMai.ps1"
if errorlevel 1 (
  echo.
  echo 系统启动未完成。请查看上方错误信息。
  pause
  exit /b 1
)
pause
