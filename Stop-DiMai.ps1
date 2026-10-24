$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '未找到 Docker。' -ForegroundColor Red
    exit 1
}
& docker compose down
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host '地脉智防服务已停止。业务数据库与知识库数据卷已保留。' -ForegroundColor Green
exit 0
