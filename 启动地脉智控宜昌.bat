@echo off
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo 未找到 Docker。请先安装 Docker Desktop。
  pause
  exit /b 1
)

docker info >nul 2>nul
if not errorlevel 1 goto docker_ready
if exist "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe" (
  echo 正在启动 Docker Desktop...
  start "" "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"
) else (
  echo 请先启动 Docker Desktop。
)
set /a tries=0
:wait_docker
docker info >nul 2>nul
if not errorlevel 1 goto docker_ready
set /a tries+=1
if %tries% geq 90 goto docker_timeout
timeout /t 2 /nobreak >nul
goto wait_docker

:docker_ready
echo 正在启动地脉智控宜昌系统。首次运行会下载并构建运行环境。
docker compose up -d --build
if errorlevel 1 (
  echo 启动失败。可查看 Docker Desktop 状态或运行：docker compose logs --tail=80
  pause
  exit /b 1
)

echo 等待宜昌系统页面和业务服务就绪...
set /a tries=0
:wait_app
curl.exe -fsS http://127.0.0.1:8011/health >nul 2>nul
if not errorlevel 1 curl.exe -fsS http://127.0.0.1:5174/p6/api/v1/dynamic/status >nul 2>nul
if not errorlevel 1 curl.exe -fsS http://127.0.0.1:5174/warning/risk-eval >nul 2>nul
if not errorlevel 1 goto open_app
set /a tries+=1
if %tries% geq 90 goto app_timeout
timeout /t 2 /nobreak >nul
goto wait_app

:open_app
start "" "http://127.0.0.1:5174/warning/risk-eval"
echo 宜昌风险评价地图：http://127.0.0.1:5174/warning/risk-eval
echo 动态风险一张图：http://127.0.0.1:5174/warning/risk-report
echo 宜昌 AI 工作台：http://127.0.0.1:5174/ai-studio
echo geo_rag 页面：http://127.0.0.1:5175/?embed=rag#/extensions?tab=knowledge
echo 停止服务请运行：停止地脉智控宜昌.bat
pause
exit /b 0

:app_timeout
echo 服务启动超时。请运行：docker compose ps
echo 查看日志请运行：docker compose logs --tail=80
pause
exit /b 1

:docker_timeout
echo Docker Desktop 尚未就绪。请检查 Docker Desktop 后重新运行本脚本。
pause
exit /b 1
