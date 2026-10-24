param([switch]$NoBrowser, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Stop-WithError([string]$Message) {
    Write-Host "启动终止：$Message" -ForegroundColor Red
    exit 1
}

foreach ($expected in @('compose.yaml', 'data/p6/P6_runtime_profile.json', 'data/yichang-scenario', 'frontend/geo-guard-fe/public/geo/yichang')) {
    if (-not (Test-Path -LiteralPath $expected)) {
        Stop-WithError "未找到 $expected。请下载 GitHub 仓库完整源码并将覆盖包安装在仓库根目录；不能只运行覆盖包。"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-WithError '未安装 Docker Desktop。请先安装并启动 Docker Desktop。'
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker/Docker/Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/Docker Desktop.exe')
    )
    $desktop = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($desktop) {
        Write-Host '正在等待 Docker Desktop 启动...'
        Start-Process -FilePath $desktop
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 2
            & docker info *> $null
            if ($LASTEXITCODE -eq 0) { break }
        }
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Docker 引擎未启动。请确认 Docker Desktop 正在运行 Linux 容器。' }
}

$envPath = Join-Path $PSScriptRoot '.env'
$credentialPath = Join-Path $PSScriptRoot '本机登录信息.txt'
if (-not (Test-Path -LiteralPath $envPath)) {
    $password = 'dzzh@2025'
    $lines = @(
        '# Generated locally. Do not publish this file.',
        "GEO_LOCAL_AUTH_PASSWORD=$password",
        '# Optional: set your own Tianditu token for online satellite imagery.',
        'VITE_TDT_TOKEN='
    )
    [System.IO.File]::WriteAllLines($envPath, $lines, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host '首次运行：已初始化本地登录配置。'
}

$content = Get-Content -LiteralPath $envPath -Encoding UTF8
$passwordLine = $content | Where-Object { $_ -match '^GEO_LOCAL_AUTH_PASSWORD=\S+' } | Select-Object -Last 1
if (-not $passwordLine) { Stop-WithError '.env 未设置 GEO_LOCAL_AUTH_PASSWORD，请补齐后重新运行。' }
$password = ($passwordLine -split '=', 2)[1]
$loginInfo = @("地脉智防（本机部署）", "访问地址：http://127.0.0.1:5174/", '账号：admin', "密码：$password", '本机 .env 文件不得上传至公开仓库。')
[System.IO.File]::WriteAllLines($credentialPath, $loginInfo, (New-Object System.Text.UTF8Encoding($false)))

& docker compose config --quiet
if ($LASTEXITCODE -ne 0) { Stop-WithError 'Compose 配置校验失败，请检查 .env 与 compose.yaml。' }
Write-Host '正在启动地脉智防六项容器服务；首次构建需要下载基础镜像和依赖。'
if ($SkipBuild) { & docker compose up -d } else { & docker compose up -d --build }
if ($LASTEXITCODE -ne 0) { Stop-WithError '容器启动失败。请运行 docker compose logs --tail=100 查看故障。' }

Write-Host '正在检查本地地图、风险数据及业务服务。'
$verified = $false
for ($i = 0; $i -lt 120; $i++) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Verify-DiMai.ps1') -Quiet *> $null
    if ($LASTEXITCODE -eq 0) { $verified = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $verified) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Verify-DiMai.ps1')
    Stop-WithError '服务未在限定时间内全部就绪。请检查上方项目或执行 docker compose logs --tail=100。'
}

Write-Host '地脉智防已就绪。' -ForegroundColor Green
Write-Host '系统入口：http://127.0.0.1:5174/warning/risk-eval'
Write-Host '协同处置：http://127.0.0.1:5174/business/cases'
Write-Host '知识库管理：http://127.0.0.1:5175/'
Write-Host "登录账号：admin；密码已保存至：$credentialPath"
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5174/warning/risk-eval' }
exit 0
