$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8011/api/v1/yichang/gold-runs'

function Call([string]$Method, [string]$Path, [object]$Body = $null) {
    $params = @{ Method=$Method; Uri=($base + $Path); TimeoutSec=90 }
    if ($null -ne $Body) {
        $params['ContentType'] = 'application/json'
        $params['Body'] = (ConvertTo-Json -InputObject $Body -Depth 8 -Compress)
    }
    Invoke-RestMethod @params
}

function Stage([string]$Label, [scriptblock]$Action) {
    Write-Host "[执行] $Label"
    try {
        $result = & $Action
        Write-Host "[通过] $Label" -ForegroundColor Green
        return $result
    } catch {
        Write-Host "[失败] ${Label}：$($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

try {
    Write-Host '协同处置业务验收将创建一条新的本地案例事件，并写入合成反馈及审核记录。'
    $confirm = Read-Host '输入 YES 继续'
    if ($confirm -cne 'YES') { exit 1 }

    $snapshot = Stage '建立秭归事件' { Call 'POST' '/GOLD-02/start' @{} }
    $runId = [string]$snapshot.run.run_id
    if (-not $runId) { throw '业务服务未返回 run_id' }
    $path = '/' + [uri]::EscapeDataString($runId)

    $null = Stage '监测异常阶段' { Call 'POST' ($path + '/stages/GOLD-02/a3/execute') @{} }
    $null = Stage '辅助决策执行' { Call 'POST' ($path + '/a4/execute') @{} }
    $null = Stage '方案审核和四项任务创建' { Call 'POST' ($path + '/plan-review') @{fixture_replay=$true} }
    $null = Stage '异常阶段任务反馈' { Call 'POST' ($path + '/feedbacks/replay') @{fixture_replay=$true;stage_id='GOLD-02'} }
    $null = Stage '恢复阶段记录' { Call 'POST' ($path + '/stages/GOLD-03') @{} }
    $null = Stage '恢复阶段监测研判' { Call 'POST' ($path + '/stages/GOLD-03/a3/execute') @{} }
    $null = Stage '恢复阶段任务反馈' { Call 'POST' ($path + '/feedbacks/replay') @{fixture_replay=$true;stage_id='GOLD-03'} }

    $snapshot = Stage '读取待复核任务' { Call 'GET' $path }
    $tasks = @($snapshot.records.task)
    if ($tasks.Count -ne 4) { throw "预期4项任务，实际$($tasks.Count)项" }
    foreach ($task in $tasks) {
        $fixtureKey = [string]$task.payload.fixture_task_key
        if (-not $fixtureKey) { throw '任务缺少追溯键' }
        $null = Stage ('任务复核 ' + $fixtureKey) {
            Call 'POST' ($path + '/task-reviews/' + [uri]::EscapeDataString($fixtureKey)) @{fixture_replay=$true}
        }
    }
    $null = Stage '生成复盘报告' { Call 'POST' ($path + '/reports/retrospective') @{execute_dify=$false} }
    $snapshot = Stage '审核报告并关闭案例事件' { Call 'POST' ($path + '/reports/final-review') @{fixture_replay=$true} }
    $snapshot = Stage '持久化回读' { Call 'GET' $path }

    if ($snapshot.run.status -ne 'completed') { throw "事件未完成：$($snapshot.run.status)" }
    $reports = @($snapshot.records.report | Where-Object { $_.payload.report_type -eq 'retrospective' -and $_.payload.review_status -eq 'approved' })
    if ($reports.Count -lt 1) { throw '未找到已审核复盘报告' }
    $reportId = [string]$reports[-1].record_id
    $docxUrl = $base + $path + '/reports/' + [uri]::EscapeDataString($reportId) + '/docx'
    $docx = Stage 'DOCX报告下载接口' { Invoke-WebRequest -UseBasicParsing -Uri $docxUrl -TimeoutSec 90 }
    if ($docx.RawContentLength -lt 500) { throw 'DOCX文件异常或为空' }

    Write-Host "`n协同处置流程已通过：事件编号 $runId" -ForegroundColor Green
    Write-Host "通过项：两阶段监测、方案审核、两阶段反馈、四项复核、报告归档、DOCX下载。"
    Write-Host '以上验收使用合成案例资料，不作为真实事件处理证明。'
    exit 0
} catch {
    Write-Host "`n业务验收终止：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host '请查看 docker compose logs geo-agent-graph --tail=100。'
    exit 1
}
