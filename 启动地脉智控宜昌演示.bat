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
echo 正在启动地脉智控宜昌演示服务。首次运行会下载并构建运行环境。
docker compose up -d --build
if errorlevel 1 (
  echo 启动失败。可查看 Docker Desktop 状态或运行：docker compose logs --tail=80
  pause
  exit /b 1
)

echo 等待宜昌演示页面和业务服务就绪...
set /a tries=0
:wait_app
curl.exe -fsS http://127.0.0.1:8011/health >nul 2>nul
if not errorlevel 1 curl.exe -fsS http://127.0.0.1:5174/demo >nul 2>nul
if not errorlevel 1 goto open_demo
set /a tries+=1
if %tries% geq 90 goto open_demo
timeout /t 2 /nobreak >nul
goto wait_app

:open_demo
start "" "http://127.0.0.1:5174/demo"
echo 演示页面：http://127.0.0.1:5174/demo
echo geo_rag 页面：http://127.0.0.1:5175/
echo 停止服务请运行：停止地脉智控宜昌演示.bat
pause
exit /b 0

:docker_timeout
echo Docker Desktop 尚未就绪。请检查 Docker Desktop 后重新运行本脚本。
pause
exit /b 1
