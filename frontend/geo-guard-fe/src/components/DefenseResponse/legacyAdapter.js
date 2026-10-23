/**
 * 还原自 detailComp-LCiSjx32.js 所使用的数据字段。
 * 前端中间工作区独立于恩施的接口/路由/Pinia/Cesium。
 * 原编译产物显示 status===1 可以“推送”；状态 4、5 禁止继续上报。
 * 其他数字状态的精确中文映射无法仅凭该页确定，保守映射为待核验/处理中。
 */
import RETREAT from './assets/retreat-CNy2oFwQ.png'
import ALARM from './assets/alarm-BSBmb51R.png'
import INSPECT from './assets/inspect-DcuL7R6n.png'
import RISK from './assets/risk-R0lM6nP-.png'
import GOVERN from './assets/govern-Dk0jtt80.png'
import PROMOTION from './assets/promotion-Q_-fQrMG.png'
import TRAFFIC from './assets/traffic-B1Dsku0r.png'
import OTHER from './assets/others-CdN2AQoL.png'

export const DEFAULT_TASK_TYPES = [
  { key: 'retreat', label: '人员安置', icon: RETREAT },
  { key: 'inspect', label: '监测巡查（群测群防）', icon: INSPECT },
  { key: 'monitor', label: '监测巡查（仪器监测）', icon: INSPECT },
  { key: 'alarm', label: '警示防护', icon: ALARM },
  { key: 'risk', label: '排危除险', icon: RISK },
  { key: 'govern', label: '治理工程', icon: GOVERN },
  { key: 'promotion', label: '宣传告知', icon: PROMOTION },
  { key: 'traffic', label: '交通管控', icon: TRAFFIC },
  { key: 'other', label: '其他任务', icon: OTHER },
]

export const STATUS_LABEL = {
  draft: '待核查',
  pending: '待推送',
  pushed: '已推送',
  processing: '处置中',
  feedback: '已反馈',
  verified: '已核验',
  closed: '已结案',
  unknown: '待核验',
}

// numericStatusMap 应由宿主用真实接口常量配置；只固化编译产物能够确定的 1/4/5 行为。
export function normalizeStatus(raw, numericStatusMap = {}) {
  if (typeof raw === 'string' && Object.hasOwn(STATUS_LABEL, raw)) return raw
  if (typeof raw === 'number') {
    if (Object.hasOwn(numericStatusMap, raw)) return numericStatusMap[raw]
    if (raw === 1) return 'pending'
    if (raw === 4 || raw === 5) return 'feedback'
    return 'unknown'
  }
  return 'unknown'
}

export function normalizeTask(task = {}, index = 0, options = {}) {
  const taskTypeMap = options.taskTypeMap ?? {}
  const rawType = task.planType ?? task.type ?? 'other'
  const type = taskTypeMap[rawType] ?? (DEFAULT_TASK_TYPES.some(x => x.key === rawType) ? rawType : 'other')
  const meta = DEFAULT_TASK_TYPES.find(x => x.key === type) ?? DEFAULT_TASK_TYPES.at(-1)
  let photos = task.photos ?? task.scenePhoto ?? []
  if (typeof photos === 'string') photos = photos.split(',').map(s => s.trim()).filter(Boolean)
  if (!Array.isArray(photos)) photos = []
  return {
    id: task.id ?? `demo-task-${index + 1}`,
    type, label: task.taskName ?? task.title ?? task.planName ?? meta.label,
    icon: meta.icon,
    status: normalizeStatus(task.status, options.numericStatusMap),
    owner: task.responsiblePerson ?? task.owner ?? '待指定',
    description: task.inspectionSuggestion ?? task.submitRequire ?? task.description ?? '',
    reporter: task.addReportUserName ?? task.reporter ?? '',
    remark: task.addRemark ?? task.remark ?? '',
    photos,
    updateAt: task.updateDate ?? task.updateAt ?? '',
  }
}

export function normalizeTasks(tasks, options) {
  return (Array.isArray(tasks) ? tasks : []).map((task, index) => normalizeTask(task, index, options))
}

export function normalizeMetrics(raw = {}, taskList = []) {
  const reachCount = raw.reachCount == null ? null : Number(raw.reachCount)
  const totalCount = raw.totalCount == null ? null : Number(raw.totalCount)
  const taskCompleteCount = Number(raw.taskCompleteCount ?? 0)
  const taskTotalCount = Number(raw.taskTotalCount ?? taskList.length)
  let completionRate = raw.completeRate
  if (completionRate == null && taskTotalCount > 0) completionRate = taskCompleteCount / taskTotalCount
  completionRate = completionRate == null ? null : Number(completionRate)
  const percentage = completionRate == null
    ? null
    : Number.isFinite(completionRate)
      ? Math.min(100, Math.max(0, completionRate <= 1 ? completionRate * 100 : completionRate))
      : null
  return { reachCount, totalCount, taskCompleteCount, taskTotalCount, percentage }
}

export function canCloseResponse(tasks) {
  return tasks.length > 0 && tasks.every(task => ['feedback', 'verified', 'closed'].includes(task.status))
}
