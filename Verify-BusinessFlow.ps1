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
        Write-Host "[失败] ${Label}：业务接口未完成，请检查本地服务状态和接口日志。" -ForegroundColor Red
        throw '秭归事件处置流程已中止。'
    }
}

try {
    Write-Host '秭归事件处置流程验收将创建新的本地事件记录，并登记各阶段处置反馈与审核结果。'
    $confirm = Read-Host '输入 YES 开始'
    if ($confirm -cne 'YES') { exit 1 }

    $snapshot = Stage '建立秭归市事件' { Call 'POST' '/GOLD-02/start' @{} }
    $runId = [string]$snapshot.run.run_id
    if (-not $runId) { throw '业务服务未返回 run_id' }
    $path = '/' + [uri]::EscapeDataString($runId)

    $null = Stage '监测告警阶段研判' { Call 'POST' ($path + '/stages/GOLD-02/a3/execute') @{} }
    $null = Stage '生成处置建议' { Call 'POST' ($path + '/a4/execute') @{} }
    $null = Stage '登记方案审核结果并创建四项任务' { Call 'POST' ($path + '/plan-review') @{fixture_replay=$true} }
    $null = Stage '登记监测告警阶段任务反馈' { Call 'POST' ($path + '/feedbacks/replay') @{fixture_replay=$true;stage_id='GOLD-02'} }
    $null = Stage '建立恢复观察阶段' { Call 'POST' ($path + '/stages/GOLD-03') @{} }
    $null = Stage '恢复阶段监测研判' { Call 'POST' ($path + '/stages/GOLD-03/a3/execute') @{} }
    $null = Stage '登记恢复观察阶段任务反馈' { Call 'POST' ($path + '/feedbacks/replay') @{fixture_replay=$true;stage_id='GOLD-03'} }

    $snapshot = Stage '读取待复核任务' { Call 'GET' $path }
    $tasks = @($snapshot.records.task)
    if ($tasks.Count -ne 4) { throw "预期4项任务，实际$($tasks.Count)项" }
    $taskNumber = 0
    foreach ($task in $tasks) {
        $taskNumber++
        $fixtureKey = [string]$task.payload.fixture_task_key
        if (-not $fixtureKey) { throw '任务缺少追溯键' }
        $null = Stage ('处置任务复核 ' + $taskNumber) {
            Call 'POST' ($path + '/task-reviews/' + [uri]::EscapeDataString($fixtureKey)) @{fixture_replay=$true}
        }
    }
    $null = Stage '生成事件处置复盘报告' { Call 'POST' ($path + '/reports/retrospective') @{execute_dify=$false} }
    $snapshot = Stage '登记报告审核结果并关闭事件' { Call 'POST' ($path + '/reports/final-review') @{fixture_replay=$true} }
    $snapshot = Stage '回读已保存记录' { Call 'GET' $path }

    if ($snapshot.run.status -ne 'completed') { throw "事件未完成：$($snapshot.run.status)" }
    $reports = @($snapshot.records.report | Where-Object { $_.payload.report_type -eq 'retrospective' -and $_.payload.review_status -eq 'approved' })
    if ($reports.Count -lt 1) { throw '未找到已审核复盘报告' }
    $reportId = [string]$reports[-1].record_id
    $docxUrl = $base + $path + '/reports/' + [uri]::EscapeDataString($reportId) + '/docx'
    $docx = Stage '处置复盘报告 DOCX 下载' { Invoke-WebRequest -UseBasicParsing -Uri $docxUrl -TimeoutSec 90 }
    if ($docx.RawContentLength -lt 500) { throw 'DOCX文件异常或为空' }

    Write-Host "`n秭归事件处置流程验收通过。" -ForegroundColor Green
    Write-Host '通过项：两阶段监测研判、方案审核、两阶段反馈、四项任务复核、报告归档、持久化回读及 DOCX 下载。'
    Write-Host '资料来源：系统内置的秭归业务资料；本次运行已在本地业务库新增事件及处置记录。'
    exit 0
} catch {
    Write-Host "`n秭归事件处置流程验收中止：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host '请查看 docker compose logs geo-agent-graph --tail=100。'
    exit 1
}
