<template>
  <div class="task-dispatch-page">
    <section class="task-workspace">
      <DefenseResponseWorkspace
        v-if="!showRetrospectiveReport"
        :event-id="eventId"
        :tasks="tasks"
        :metrics="metrics"
        :active-stage="activeStage"
        :skip-plan="false"
        :loading="loading"
        :numeric-status-map="numericStatusMap"
        :task-type-map="taskTypeMap"
        @back="backToCockpit"
        @refresh="loadTasks"
        @push-all="handlePushAll"
        @push-task="handlePushTask"
        @submit-feedback="handleFeedback"
        @archive-request="handleArchiveRequest"
        @report-request="handleReportRequest"
      />
      <ReportDocumentSection
        v-else
        :event="reportEvent"
        :markdown="reportMarkdown"
        @back="showRetrospectiveReport = false"
      />
      <div v-if="refreshNotice" class="task-refresh-notice" role="status">{{ refreshNotice }}</div>
    </section>

    <aside class="assistant-column" aria-label="脉知智能助手">
      <section class="assistant-event-card">
        <header class="assistant-brandline">
          <strong>脉知</strong><span aria-hidden="true">|</span><h1>地脉智防智能助手</h1>
        </header>
        <video
          class="assistant-mascot"
          src="/video/idle.webm"
          autoplay
          muted
          loop
          playsinline
          preload="metadata"
          aria-label="脉知待机动画"
        ></video>
        <div class="priority-event">
          <h2><span aria-hidden="true">✣</span>当前优先事件</h2>
          <div class="priority-event-title">
            <i class="priority-alert" aria-hidden="true">!</i>
            <strong>{{ eventName || '暂无关联事件' }}</strong>
            <span v-if="context.riskLevel" class="risk-tag">{{ context.riskLevel }}</span>
          </div>
          <dl class="event-details">
            <div><dt>发生时间</dt><dd>{{ context.discoveryAt || context.occurrenceTime || '--' }}</dd></div>
            <div><dt>发生位置</dt><dd>{{ context.location || context.displayAddress || '--' }}</dd></div>
            <div><dt>事件类型</dt><dd>{{ context.eventType || context.eventTypeName || '--' }}</dd></div>
          </dl>
          <div class="event-card-footer">
            <span v-if="eventId">事件编号：{{ eventId }}</span>
            <span v-else>等待关联事件</span>
            <el-button type="primary" :disabled="!eventId" @click="backToCockpit">进入事件</el-button>
          </div>
        </div>
      </section>

      <section class="assistant-chat-card" aria-label="脉知对话">
        <ChatBox
          v-model="chatMessages"
          :assistant-avatar="maizhiAvatar"
          :yichang-qa-enabled="true"
          input-placeholder="请输入您的问题..."
        />
      </section>
    </aside>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'
import ChatBox from '@/components/ChatBox/index.vue'
import { Components } from '@/components/ChatBox/config.js'
import DefenseResponseWorkspace from '@/components/DefenseResponse/DefenseResponseWorkspace.vue'
import { normalizeTasks } from '@/components/DefenseResponse/legacyAdapter.js'
import { taskDistList, pushTaskDistList, uploadTaskPhotos, submitTaskFeedback } from '@/api/task.js'
import { useUserStore } from '@/store/user.js'
import { storeToRefs } from 'pinia'
import maizhiAvatar from '@/assets/imgs/home/maizhi-avatar.png'
import ReportDocumentSection from '@/components/ReviewReportInner/components/ReportDocumentSection.vue'
import { buildRetrospectiveReportMarkdown } from './retrospectiveReport.js'

defineOptions({ name: 'TaskDispatchPage' })

const CONTEXT_KEY = 'geoGuard:cockpit:task-dispatch:context'
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const { userInfo } = storeToRefs(userStore)

const numericStatusMap = { 1: 'pending', 3: 'processing', 4: 'closed', 5: 'feedback' }
const taskTypeMap = {
  1: 'retreat', 2: 'alarm', 3: 'inspect', 4: 'risk', 5: 'govern',
  6: 'promotion', 7: 'traffic', 8: 'other', 9: 'monitor',
}

function readContext() {
  const storedContexts = [sessionStorage, localStorage].map((storage) => {
    try {
      return JSON.parse(storage.getItem(CONTEXT_KEY) || '{}')
    } catch (_) {
      return {}
    }
  })
  const requestedIds = [route.query.event_id, route.query.eventId, route.query.eventKey]
    .map((value) => String(value || ''))
    .filter(Boolean)
  const saved = storedContexts.find((candidate) => {
    const ids = [candidate.sourceEventId, candidate.event_id, candidate.eventKey, candidate.slopeUnitId]
      .map((value) => String(value || ''))
    return requestedIds.length ? requestedIds.some((id) => ids.includes(id)) : Boolean(candidate.eventKey || candidate.sourceEventId || candidate.event_id)
  }) || {}
  const sourceEventId = route.query.event_id || route.query.eventId || saved.sourceEventId || saved.event_id || ''
  const eventKey = route.query.eventKey || saved.eventKey || sourceEventId || ''
  const queryHandle = route.query.handleId || route.query.id || ''
  return {
    ...saved,
    sourceEventId: String(sourceEventId || ''),
    eventKey: String(eventKey || ''),
    planHandleId: saved.planHandleId || saved.handleId || saved.defRespPlanId || queryHandle || '',
  }
}

const context = ref(readContext())
const eventId = computed(() => context.value.sourceEventId || context.value.eventKey || '')
const eventName = computed(() => context.value.eventName || context.value.title || '')
const reportEvent = computed(() => ({
  title: eventName.value || '秭归市事件',
  eventId: eventId.value || '--',
  occurredAt: context.value.discoveryAt || context.value.occurrenceTime || context.value.eventTime || '--',
  location: context.value.location || context.value.displayAddress || context.value.address || '--',
  disasterType: context.value.eventTypeName || context.value.eventType || '滑坡险情',
  riskLevel: context.value.riskLevel || '待核实',
}))
const reportMarkdown = computed(() => buildRetrospectiveReportMarkdown(reportEvent.value))
const showRetrospectiveReport = ref(false)
const taskHandleId = computed(() => {
  const value = String(context.value.planHandleId || '')
  return /^\d+$/.test(value) ? value : ''
})
const tasks = ref([])
const loading = ref(false)
const hasLoadedRealTasks = ref(false)
const refreshNotice = ref('')
const activeStage = ref(3)

function makeBubble(type, content) {
  return {
    comp: Components.BUBBLE,
    props: { type, avatarSrc: maizhiAvatar, message: { content, completed: true }, gap: 22 },
  }
}

const chatMessages = ref([
  makeBubble(1, '您好，我是脉知，可结合当前事件与任务协同信息，协助分析处置进展和后续建议。'),
])

const normalizedTasks = computed(() => normalizeTasks(tasks.value, { numericStatusMap, taskTypeMap }))
const metrics = computed(() => {
  const completed = normalizedTasks.value.filter((task) => ['feedback', 'verified', 'closed'].includes(task.status)).length
  return {
    reachCount: null,
    totalCount: null,
    taskCompleteCount: completed,
    taskTotalCount: tasks.value.length,
    completeRate: tasks.value.length ? completed / tasks.value.length : null,
  }
})

function extractRows(response) {
  if (Array.isArray(response?.data)) return response.data
  if (Array.isArray(response?.rows)) return response.rows
  if (Array.isArray(response?.data?.rows)) return response.data.rows
  return null
}

async function loadTasks() {
  refreshNotice.value = ''
  if (!taskHandleId.value) {
    tasks.value = []
    refreshNotice.value = hasLoadedRealTasks.value
      ? '未取得响应方案编号，无法按当前事件刷新后端任务。'
      : '当前事件尚未关联处置任务，请先在协同处置中心建立并审核处置方案。'
    return
  }

  loading.value = true
  try {
    const response = await taskDistList({
      handleId: taskHandleId.value,
      sourceType: 4,
      pageNum: 1,
      pageSize: 100,
    })
    if (response instanceof Error || response?.isAxiosError) throw response
    if (response?.code != null && Number(response.code) !== 200) {
      throw new Error(response.msg || '任务列表请求失败')
    }
    const rows = extractRows(response)
    if (!rows) throw new Error('任务列表返回结构无法识别')
    tasks.value = rows
    hasLoadedRealTasks.value = true
  } catch (error) {
    if (!hasLoadedRealTasks.value) {
      tasks.value = []
      refreshNotice.value = '任务列表暂时不可用，请检查事件关联和服务状态后重试。'
    } else {
      refreshNotice.value = '后端任务状态暂未刷新，当前保留上次读取的数据。'
      ElMessage.warning('任务状态刷新失败；当前页面未修改后端任务')
    }
    console.warn('读取防御响应任务失败', error)
  } finally {
    loading.value = false
  }
}

function backToCockpit() {
  const query = {}
  if (context.value.eventKey) query.eventKey = context.value.eventKey
  if (eventId.value) query.event_id = eventId.value
  router.push({ name: 'CockpitHome', query })
}

function normalizeIds(values) {
  return [...new Set((values || []).map((value) => Number(value)).filter((value) => Number.isSafeInteger(value) && value > 0))]
}

async function pushTaskIds(values) {
  const taskIds = normalizeIds(values)
  if (!taskIds.length) {
    ElMessage.info('当前任务缺少有效的后端任务编号，未提交推送')
    return
  }
  try {
    await pushTaskDistList({ taskIds })
    ElMessage.info('推送请求已返回，正在读取后端任务状态')
    await loadTasks()
  } catch (error) {
    console.warn('任务推送未完成', error)
    ElMessage.warning('推送请求未完成；请核对任务状态后重试')
  }
}

function handlePushAll(payload) {
  pushTaskIds(payload?.taskIds)
}

function handlePushTask(payload) {
  pushTaskIds([payload?.taskId])
}

function getCurrentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('当前浏览器不支持定位'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve(coords),
      reject,
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 },
    )
  })
}

async function handleFeedback(payload) {
  const [taskId] = normalizeIds([payload?.taskId])
  if (!taskId) {
    ElMessage.info('当前任务缺少有效的后端任务编号，未提交反馈')
    return
  }
  if (!Array.isArray(payload?.files) || payload.files.length < 2) {
    ElMessage.warning('现场反馈至少需要两张照片，尚未提交')
    return
  }

  try {
    const coords = await getCurrentPosition()
    const uploadResult = await uploadTaskPhotos(taskId, payload.files)
    const photos = Array.isArray(uploadResult) ? uploadResult : uploadResult?.data
    if (!Array.isArray(photos) || photos.length < 2) {
      throw new Error('照片上传未返回足够的文件编号')
    }
    const submitTime = dayjs().format('YYYY-MM-DD HH:mm:ss')
    const user = userInfo.value?.user || userInfo.value || {}
    await submitTaskFeedback({
      taskId,
      inspectorId: user.userId ? Number(user.userId) : undefined,
      inspectorName: payload.reporter,
      inspectorPhone: user.phonenumber || user.phoneNumber || undefined,
      checkInTime: submitTime,
      checkInCenter: `POINT(${coords.longitude} ${coords.latitude})`,
      photos,
      textRecord: payload.remark,
      submitTime,
      status: 5,
    })
    ElMessage.info('反馈已提交接口，正在核对后端任务状态')
    await loadTasks()
  } catch (error) {
    console.warn('现场反馈未完成', error)
    ElMessage.warning(error?.message || '现场反馈未提交；请检查定位、照片和任务状态')
  }
}

function handleArchiveRequest() {
  ElMessage.info('请在协同处置中心核实并完成当前事件归档。')
}

function handleReportRequest() {
  const event = reportEvent.value
  showRetrospectiveReport.value = true
  chatMessages.value = [
    ...chatMessages.value,
    makeBubble(2, `整理「${event.title}」的处置复盘报告`),
    makeBubble(1, '报告依据当前事件已保存的调查记录、任务反馈与恢复复核信息生成，审核后可归档。'),
    {
      comp: Components.RETROSPECTIVE_TRACE,
      props: {
        eventName: event.title,
        eventId: event.eventId,
        eventTime: event.occurredAt,
        location: event.location,
      },
      show: true,
    },
  ]
}

function handleContextStorageChange(event) {
  if (event.key !== CONTEXT_KEY || !event.newValue) return
  try {
    const nextContext = JSON.parse(event.newValue)
    const nextEventId = String(nextContext.sourceEventId || nextContext.event_id || nextContext.eventKey || '')
    if (!nextEventId) return
    const previousEventId = eventId.value
    const previousHandleId = taskHandleId.value
    context.value = {
      ...nextContext,
      sourceEventId: String(nextContext.sourceEventId || nextContext.event_id || ''),
      eventKey: String(nextContext.eventKey || nextEventId),
      planHandleId: nextContext.planHandleId || nextContext.handleId || nextContext.defRespPlanId || '',
    }
    if (previousEventId !== eventId.value || previousHandleId !== taskHandleId.value) {
      tasks.value = []
      hasLoadedRealTasks.value = false
      loadTasks()
    }
  } catch (_) {}
}

onMounted(() => {
  window.addEventListener('storage', handleContextStorageChange)
  loadTasks()
})

onBeforeUnmount(() => window.removeEventListener('storage', handleContextStorageChange))
</script>

<style lang="less" scoped>
.task-dispatch-page {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(390px, 26vw, 520px);
  gap: 12px;
  padding: 10px;
  box-sizing: border-box;
  overflow: hidden;
  color: #233449;
  background: #e9f5ff;
  font-family: var(--gg-font-ui, 'Microsoft YaHei', 'PingFang SC', sans-serif);
}

.task-workspace {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.task-workspace :deep(.report-document-section) {
  height: 100%;
  border-radius: 18px;
}

.task-workspace :deep(.yc-defense-workspace) {
  padding: 12px;
  background: transparent;
}

.task-workspace :deep(.yc-defense-panel) {
  padding: 18px 20px 12px;
  border: 1px solid #e6f0fa;
  box-shadow: 0 4px 16px rgba(32, 100, 173, 0.04);
}

.task-workspace :deep(.yc-defense-metrics) {
  gap: 16px;
  margin-bottom: 20px;
}

.task-workspace :deep(.yc-defense-grid) {
  gap: 16px;
}

.task-workspace :deep(.dr-task-card) {
  min-height: 260px;
}

.task-refresh-notice {
  position: absolute;
  top: 20px;
  right: 24px;
  z-index: 3;
  max-width: min(420px, 60%);
  padding: 8px 12px;
  border: 1px solid #f1d8a7;
  border-radius: 8px;
  background: #fffaf0;
  color: #94651d;
  font-size: 12px;
}

.assistant-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  min-height: 0;
  padding: 8px 6px 8px 0;
}

.assistant-event-card,
.assistant-chat-card {
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #e5eff8;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 4px 18px rgba(34, 103, 173, 0.05);
}

.assistant-event-card {
  flex: none;
  height: 260px;
  padding: 16px 18px 12px;
  box-sizing: border-box;
  background: linear-gradient(145deg, #f8fcff 0%, #fff 76%);
}

.assistant-brandline {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding-right: 130px;
  color: #087cff;
  white-space: nowrap;
}

.assistant-brandline strong {
  font-size: 27px;
  line-height: 1;
  font-weight: 800;
}

.assistant-brandline span {
  color: #68aaff;
  font-size: 24px;
  font-weight: 300;
}

.assistant-brandline h1 {
  overflow: hidden;
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  text-overflow: ellipsis;
}

.assistant-mascot {
  position: absolute;
  z-index: 2;
  top: 42px;
  right: 10px;
  width: 142px;
  height: 146px;
  object-fit: contain;
  pointer-events: none;
}

.priority-event {
  position: relative;
  z-index: 1;
  margin-top: 10px;
  padding: 10px 12px 9px;
  border: 1px solid #e3effc;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.9);
}

.priority-event h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
  color: #243a5a;
  font-size: 14px;
  font-weight: 700;
}

.priority-event h2 span {
  color: #66a6ff;
  font-size: 17px;
}

.priority-event-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-right: 112px;
}

.priority-event-title strong {
  min-width: 0;
  overflow: hidden;
  color: #087cff;
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.priority-alert {
  display: grid;
  flex: none;
  width: 21px;
  height: 21px;
  place-items: center;
  border-radius: 50%;
  background: #f34444;
  color: #fff;
  font-size: 13px;
  font-style: normal;
  font-weight: 700;
}

.risk-tag {
  flex: none;
  padding: 3px 8px;
  border: 1px solid #ffd5a4;
  border-radius: 6px;
  background: #fff2df;
  color: #e17916;
  font-size: 11px;
}

.event-details {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
  padding-right: 112px;
}

.event-details div {
  display: grid;
  grid-template-columns: 62px minmax(0, 1fr);
  gap: 7px;
  min-width: 0;
  font-size: 12px;
  line-height: 1.45;
}

.event-details dt {
  color: #71839a;
}

.event-details dd {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: #314864;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 9px;
  padding-left: 28px;
  color: #98a8ba;
  font-size: 10px;
}

.event-card-footer .el-button {
  min-width: 92px;
  height: 34px;
  border-radius: 7px;
  font-weight: 700;
}

.assistant-chat-card {
  flex: 1;
  min-height: 0;
  padding: 12px;
}

.assistant-chat-card :deep(.chat-box) {
  position: relative;
  width: 100%;
  height: 100%;
  padding: 0;
  box-sizing: border-box;
}

.assistant-chat-card :deep(.model-send) {
  display: flex;
  height: calc(100% - 126px);
  flex-direction: column;
  justify-content: flex-start;
  overflow-y: auto;
}

.assistant-chat-card :deep(.model-input) {
  position: absolute;
  right: 4px;
  bottom: 2px;
  left: 4px;
  width: auto;
  height: 104px;
}

.assistant-chat-card :deep(.input-box) {
  height: 100%;
  padding: 11px;
  box-sizing: border-box;
  border: 1px solid #8fc2ff;
  border-radius: 13px;
  box-shadow: 0 2px 8px rgba(38, 117, 239, 0.1);
}

.assistant-chat-card :deep(.input-box .el-textarea__inner) {
  min-height: 48px !important;
  padding: 10px 12px;
  font-size: 14px;
}

.assistant-chat-card :deep(.input-box .foot-operate) {
  padding: 2px 8px 7px;
}

.assistant-chat-card :deep(.input-box .submit) {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: linear-gradient(135deg, #219cff, #087af5);
}

.assistant-chat-card :deep(.input-box .submit img) {
  width: 22px;
  height: 22px;
}

.assistant-chat-card :deep(.input-tip),
.assistant-chat-card :deep(.model-input .operate-box) {
  display: none;
}

@media (max-width: 1350px) {
  .task-dispatch-page {
    grid-template-columns: minmax(0, 1fr) minmax(340px, 36%);
  }

  .task-workspace :deep(.yc-defense-panel) {
    padding: 14px;
  }

  .task-workspace :deep(.yc-defense-grid) {
    gap: 10px;
  }
}

@media (max-width: 980px) {
  .task-dispatch-page {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(680px, 1fr) minmax(420px, 0.8fr);
    overflow-y: auto;
  }

  .assistant-column {
    padding: 0 12px 12px;
  }
}
</style>
