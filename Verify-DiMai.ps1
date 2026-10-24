param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$failures = New-Object System.Collections.Generic.List[string]

function Check([string]$Name, [scriptblock]$Action) {
    try {
        & $Action
        if (-not $Quiet) { Write-Host "[通过] $Name" -ForegroundColor Green }
    } catch {
        $message = $_.Exception.Message
        $failures.Add("$Name：$message")
        if (-not $Quiet) { Write-Host "[失败] ${Name}：$message" -ForegroundColor Red }
    }
}

function Http([string]$Url, [switch]$Json) {
    $reply = Invoke-WebRequest -Uri $Url -TimeoutSec 8 -UseBasicParsing
    if ($reply.StatusCode -lt 200 -or $reply.StatusCode -ge 300) { throw "HTTP $($reply.StatusCode)" }
    if ($Json) { $null = ConvertFrom-Json -InputObject $reply.Content }
}

Check 'Docker 引擎' {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker 未安装' }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop 未运行' }
}
Check '容器配置和健康状态' {
    & docker compose config --quiet *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Compose 配置无效' }
    $services = @(& docker compose ps --services --status running)
    if ($LASTEXITCODE -ne 0) { throw '读取容器状态失败' }
    foreach ($name in @('p6-api','geo-rag-api','geo-agent-graph','auth-api','yichang-web','geo-rag-ui')) {
        if ($services -notcontains $name) { throw "$name 未处于运行状态" }
    }
}
Check '系统主入口' { Http 'http://127.0.0.1:5174/cockpit' }
Check '动态风险数据' { Http 'http://127.0.0.1:5174/p6/api/v1/dynamic/status' -Json }
Check '本地地形配置' { Http 'http://127.0.0.1:5174/geo/yichang/terrain/layer.json' -Json }
Check '本地地理图层配置' { Http 'http://127.0.0.1:5174/geo/yichang/frontend_layers.json' -Json }
Check '多智能体业务接口' { Http 'http://127.0.0.1:8011/health' -Json }
Check '知识库工作台' { Http 'http://127.0.0.1:5175/' }

if ($failures.Count -gt 0) {
    if (-not $Quiet) {
        Write-Host "`n未通过 $($failures.Count) 项。检查容器日志：docker compose logs --tail=100" -ForegroundColor Yellow
        foreach ($issue in $failures) { Write-Host "- $issue" }
    }
    exit 1
}
if (-not $Quiet) {
    Write-Host "`n8项部署核验已通过。" -ForegroundColor Green
    Write-Host '说明：基础健康检查不代表大模型、真实监测设备与正式行政系统已经接入。'
}
exit 0
