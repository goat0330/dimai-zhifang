const GOLD_API = '/yichang-gold/api/v1/yichang'

async function request(path, options = {}) {
  const response = await fetch(GOLD_API + path, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  })

  if (!response.ok) {
    let message = ''
    try {
      const body = await response.json()
      message = body.detail || body.message || ''
    } catch (_) {}
    throw new Error(message || '业务演示接口请求失败（' + response.status + '）')
  }

  return response
}

const post = (path, body = {}) => request(path, {
  method: 'POST',
  body: JSON.stringify(body),
}).then((response) => response.json())

export const readGoldRun = (runId) => (
  request('/gold-runs/' + encodeURIComponent(runId))
    .then((response) => response.json())
)

export const startGoldRun = (scenarioId) => (
  post('/gold-runs/' + encodeURIComponent(scenarioId) + '/start')
)

export const executeGoldA2 = (runId) => post('/gold-runs/' + encodeURIComponent(runId) + '/a2/execute')

export const executeGoldA3 = (runId, stageId) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/stages/' + encodeURIComponent(stageId) + '/a3/execute')
)

export const executeGoldA4 = (runId) => post('/gold-runs/' + encodeURIComponent(runId) + '/a4/execute')

export const executeGoldA5Investigation = (runId) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/a5/investigation/execute')
)

export const reviewGoldPlan = (runId) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/plan-review', { fixture_replay: true })
)

export const replayGoldFeedback = (runId, stageId) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/feedbacks/replay', {
    fixture_replay: true,
    stage_id: stageId,
  })
)

export const executeGoldRecovery = (runId) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/stages/GOLD-03')
)

export const reviewGoldTask = (runId, taskFixtureKey) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/task-reviews/' + encodeURIComponent(taskFixtureKey), {
    fixture_replay: true,
  })
)

export const createGoldRetrospective = (runId, executeDify = false) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/reports/retrospective', {
    execute_dify: executeDify,
  })
)

export const reviewGoldFinalReport = (runId) => (
  post('/gold-runs/' + encodeURIComponent(runId) + '/reports/final-review', { fixture_replay: true })
)

export const queryGold = (query) => post('/qa', { query, workflow: 'qa' })

export const downloadGoldReport = async (runId, reportId) => {
  const response = await request(
    '/gold-runs/' + encodeURIComponent(runId) + '/reports/' + encodeURIComponent(reportId) + '/docx',
  )
  return response.blob()
}
