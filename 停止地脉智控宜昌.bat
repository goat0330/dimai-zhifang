@echo off
setlocal
cd /d "%~dp0"
docker compose down
if errorlevel 1 (
  echo 停止失败。请确认 Docker Desktop 正在运行。
  pause
  exit /b 1
)
echo 地脉智控宜昌系统已停止。本机保存的数据仍保留。
pause
