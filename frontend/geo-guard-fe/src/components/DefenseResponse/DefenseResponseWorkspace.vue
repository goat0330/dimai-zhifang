<template>
  <div class="yc-defense-workspace" :class="{ 'yc-defense-loading': loading }">
    <DefenseResponseStages :active-stage="stage" :skip-plan="skipPlan" @back="emit('back')" />
    <main class="yc-defense-panel">
      <div class="yc-defense-section-head">
        <div class="yc-defense-section-title">
          <span class="yc-defense-point"></span><h2>执行跟踪看板</h2>
          <span class="yc-defense-chip" :class="{ archived: isArchived }">{{ isArchived ? '已归档' : '单点响应中' }}</span>
        </div>
        <div class="yc-defense-head-actions">
          <button class="yc-defense-text-btn" type="button" @click="requestRefresh">↻ 刷新</button>
          <button class="yc-defense-archive" type="button" :disabled="isArchived || !allFeedback" :title="!allFeedback ? '所有任务完成现场反馈后方可结束响应' : ''" @click="requestArchive">
            结束响应并归档
          </button>
        </div>
      </div>
      <div v-if="loading" class="yc-defense-alert">数据加载中…</div>
      <div v-if="localNotice && !demoMode" class="yc-defense-alert" role="status">{{ localNotice }}</div>
      <div class="yc-defense-metrics">
        <div class="yc-defense-metric"><div>群众短信触达</div><strong>{{ m.reachCount ?? '--' }}<small>/{{ m.totalCount ?? '--' }}</small></strong></div>
        <div class="yc-defense-metric"><div>处置任务触达</div><strong>{{ m.taskCompleteCount }}<small>/{{ m.taskTotalCount }}</small></strong></div>
        <div class="yc-defense-metric yc-defense-rate">
          <div><div>处置进度</div><strong>{{ m.percentage == null ? '--' : m.percentage.toFixed(0) }}<small>%</small></strong></div>
          <div class="yc-defense-ring" :style="{ '--progress': (m.percentage ?? 0) + '%' }"><span></span></div>
        </div>
      </div>
      <div class="yc-defense-section-head yc-defense-feedback-head">
        <div class="yc-defense-section-title"><span class="yc-defense-point"></span><h2>实时反馈</h2><span class="yc-defense-small-count">{{ currentTasks.length }} 项任务</span></div>
        <div class="yc-defense-head-actions">
          <span v-if="currentTasks.length && !allFeedback" class="yc-defense-hint">所有任务完成反馈后才能归档</span>
          <button v-if="!isArchived" type="button" class="yc-defense-push-all" :disabled="!hasPushable" @click="requestPushAll">➤ 批量推送</button>
          <button v-if="isArchived" type="button" class="yc-defense-push-all" @click="requestReport">查看 / 生成复盘报告</button>
        </div>
      </div>
      <div class="yc-defense-grid">
        <DefenseResponseTaskCard v-for="task in currentTasks" :key="task.id" :task="task" :selected="selectedTask === task.id" :archived="isArchived"
          @select="selectedTask = $event" @push="requestPush" @feedback="openFeedback" @preview-photo="openPhoto" />
        <div v-if="!currentTasks.length" class="yc-defense-empty">暂无任务数据；请从业务系统传入当前事件的任务列表。</div>
      </div>
      <div class="yc-defense-bottom-note">
        <span>事件编号：{{ eventId || '未指定' }}　｜　流程：方案接入 → 响应执行 → 闭环归档</span>
        <button type="button" @click="requestReport">{{ isArchived ? '查看复盘报告' : '生成复盘报告' }} →</button>
      </div>
    </main>

    <div v-if="feedbackDialog" class="yc-defense-modal-mask" @click.self="feedbackDialog = false">
      <div class="yc-defense-modal" role="dialog" aria-modal="true" aria-label="现场反馈">
        <div class="yc-defense-modal-head"><h3>现场任务反馈</h3><button type="button" @click="feedbackDialog = false">×</button></div>
        <p>任务：{{ selectedTaskName }}</p>
        <label>上报人员 <input v-model.trim="feedbackForm.reporter" placeholder="填写上报人员姓名" /></label>
        <label>现场文字记录 <textarea v-model.trim="feedbackForm.remark" rows="4" placeholder="如实填写核查与处置过程；不要使用自动生成的假记录" /></label>
        <label>现场照片（提交时上传；至少2张） <input type="file" accept="image/*" multiple @change="handleFileChange" /></label>
        <p class="yc-defense-file-tip">提交时将请求浏览器获取当前位置作为现场打卡坐标。</p>
        <p v-if="feedbackForm.files.length" class="yc-defense-file-tip">已选 {{ feedbackForm.files.length }} 张照片，等待宿主接口上传。</p>
        <div class="yc-defense-modal-actions"><button type="button" @click="feedbackDialog = false">取消</button><button class="primary" type="button" :disabled="!feedbackForm.reporter || !feedbackForm.remark || (!demoMode && feedbackForm.files.length < 2)" @click="submitFeedback">提交反馈</button></div>
      </div>
    </div>
    <div v-if="photoDialog" class="yc-defense-photo-mask" @click.self="photoDialog = null">
      <button type="button" @click="photoDialog = null">关闭 ×</button>
      <img :src="photoDialog" alt="现场照片预览" />
    </div>
  </div>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import DefenseResponseStages from './DefenseResponseStages.vue'
import DefenseResponseTaskCard from './DefenseResponseTaskCard.vue'
import { normalizeTasks, normalizeMetrics, canCloseResponse } from './legacyAdapter.js'

const props = defineProps({
  eventId: { type: [String, Number], default: '' },
  tasks: { type: Array, default: () => [] },
  metrics: { type: Object, default: () => ({}) },
  activeStage: { type: Number, default: 3 }, // 对应原流程索引 2=方案接入 3=响应执行 4=归档
  skipPlan: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  demoMode: { type: Boolean, default: false },
  numericStatusMap: { type: Object, default: () => ({}) },
  taskTypeMap: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['back', 'refresh', 'push-all', 'push-task', 'submit-feedback', 'archive-request', 'report-request', 'task-select'])
const localTasks = ref([])
const localStage = ref(props.activeStage)
const localNotice = ref('')
const selectedTask = ref(null)
const feedbackDialog = ref(false)
const photoDialog = ref(null)
const feedbackTask = ref(null)
const feedbackForm = reactive({ reporter: '', remark: '', files: [] })
const normalizeOptions = computed(() => ({ numericStatusMap: props.numericStatusMap, taskTypeMap: props.taskTypeMap }))
const stage = computed(() => props.demoMode ? localStage.value : props.activeStage)
const isArchived = computed(() => stage.value >= 4)
const currentTasks = computed(() => props.demoMode ? localTasks.value : normalizeTasks(props.tasks, normalizeOptions.value))
const allFeedback = computed(() => canCloseResponse(currentTasks.value))
const hasPushable = computed(() => currentTasks.value.some(x => x.status === 'pending'))
const completedCount = computed(() => currentTasks.value.filter(x => ['feedback', 'verified', 'closed'].includes(x.status)).length)
const m = computed(() => {
  const value = props.demoMode ? { ...props.metrics, taskTotalCount: currentTasks.value.length, taskCompleteCount: completedCount.value } : props.metrics
  // 统计数据缺失时，根据任务状态计算处置比例。
  if (props.demoMode) value.completeRate = currentTasks.value.length ? completedCount.value / currentTasks.value.length : 0
  return normalizeMetrics(value, currentTasks.value)
})
const selectedTaskName = computed(() => currentTasks.value.find(t => t.id === feedbackTask.value)?.label ?? '未知任务')
watch(() => props.tasks, value => { localTasks.value = normalizeTasks(value, normalizeOptions.value) }, { immediate: true, deep: true })
watch(() => props.activeStage, value => { localStage.value = value })
watch(selectedTask, value => { if (value != null) emit('task-select', { eventId: props.eventId, taskId: value }) })
function requestRefresh() { if (!props.demoMode) emit('refresh') }
function updateLocalTask(id, change) { if (!props.demoMode) return; localTasks.value = localTasks.value.map(t => t.id === id ? { ...t, ...change } : t) }
function requestPushAll() {
  const ids = currentTasks.value.filter(t => t.status === 'pending').map(t => t.id)
  if (!ids.length) return
  if (props.demoMode) ids.forEach(id => updateLocalTask(id, { status: 'pushed' }))
  else emit('push-all', { eventId: props.eventId, taskIds: ids })
}
function requestPush(id) {
  if (props.demoMode) updateLocalTask(id, { status: 'pushed' })
  else emit('push-task', { eventId: props.eventId, taskId: id })
}
function openFeedback(id) {
  feedbackTask.value = id; feedbackForm.reporter = ''; feedbackForm.remark = ''; feedbackForm.files = []; feedbackDialog.value = true
}
function handleFileChange(event) { feedbackForm.files = Array.from(event.target?.files ?? []) }
function submitFeedback() {
  if (!feedbackTask.value || !feedbackForm.reporter || !feedbackForm.remark) return
  const payload = { eventId: props.eventId, taskId: feedbackTask.value, reporter: feedbackForm.reporter, remark: feedbackForm.remark, files: [...feedbackForm.files] }
  if (props.demoMode) updateLocalTask(payload.taskId, { status: 'feedback', reporter: payload.reporter, remark: payload.remark })
  else emit('submit-feedback', payload)
  feedbackDialog.value = false
}
function requestArchive() {
  if (!allFeedback.value || isArchived.value) return
  if (props.demoMode) localStage.value = 4
  else emit('archive-request', { eventId: props.eventId, taskIds: currentTasks.value.map(x => x.id) })
}
function requestReport() {
  emit('report-request', { eventId: props.eventId })
}
function openPhoto(photo) {
  if (typeof photo === 'string' && (/^(https?:|data:|blob:)/).test(photo)) photoDialog.value = photo
  else localNotice.value = '此照片是原业务文件ID，需宿主使用现有 getImageUrlById 先解析可访问URL。'
}
</script>
<style scoped>
.yc-defense-workspace{width:100%;height:100%;min-height:0;display:flex;flex-direction:column;box-sizing:border-box;color:#233449;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;background:#e9f5ff;padding:20px 16px;overflow:hidden}
.yc-defense-workspace *{box-sizing:border-box}
.yc-defense-panel{background:#fff;border-radius:18px;padding:17px 20px 12px;flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column}
.yc-defense-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px;flex-shrink:0}
.yc-defense-section-title{display:flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap}
.yc-defense-section-title h2{font-size:16px;font-weight:700;color:#17273d;margin:0}
.yc-defense-point{width:6px;height:6px;background:#3561fa;flex-shrink:0}
.yc-defense-chip{background:#ffeced;border:1px solid #ffc4ca;color:#ef5659;border-radius:14px;font-size:12px;padding:3px 9px}
.yc-defense-chip.archived{background:#e1f7ed;border-color:#a6e6c7;color:#16945c}
.yc-defense-head-actions{display:flex;align-items:center;gap:12px}
.yc-defense-text-btn{background:transparent;border:0;color:#758fb7;font-size:12px;cursor:pointer}
.yc-defense-archive{border:0;border-radius:6px;padding:9px 15px;background:#3561fa;color:white;font-size:12px;cursor:pointer}
.yc-defense-archive:disabled{background:#a4c8f8;cursor:not-allowed}
.yc-defense-alert{padding:9px 12px;margin-bottom:10px;border:1px solid #d7e4fc;background:#f0f6ff;border-radius:8px;font-size:12px;color:#3666b9}
.yc-defense-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-bottom:25px;flex-shrink:0}
.yc-defense-metric{min-height:95px;border-radius:12px;background:#f5f7fa;padding:19px 22px;color:#7a8da6;font-size:13px}
.yc-defense-metric strong{display:block;margin-top:5px;font-size:28px;color:#101f35;font-weight:800;line-height:1.2}
.yc-defense-metric strong small{font-size:25px;font-weight:700}
.yc-defense-rate{display:flex;align-items:center;justify-content:space-between;gap:10px}
.yc-defense-ring{width:52px;height:52px;border-radius:50%;background:conic-gradient(#ff8c5b var(--progress),#fae7e1 var(--progress));display:grid;place-items:center}
.yc-defense-ring span{width:40px;height:40px;border-radius:50%;background:#f5f7fa}
.yc-defense-feedback-head{margin-top:4px;margin-bottom:17px}
.yc-defense-small-count,.yc-defense-hint{font-size:12px;color:#899cb6}
.yc-defense-push-all{border:0;border-radius:6px;background:#3561fa;color:#fff;font-size:13px;padding:8px 16px;cursor:pointer}
.yc-defense-push-all:disabled{background:#b2c9f4;cursor:not-allowed}
.yc-defense-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;align-items:stretch;min-height:0}
.yc-defense-empty{grid-column:1/-1;border:1px dashed #bccde4;padding:50px;text-align:center;color:#8796ae;border-radius:10px}
.yc-defense-bottom-note{padding:15px 2px 2px;display:flex;gap:10px;align-items:center;justify-content:space-between;font-size:12px;color:#9aa9bb}
.yc-defense-bottom-note button{border:0;background:transparent;color:#3561fa;cursor:pointer;white-space:nowrap}
.yc-defense-modal-mask{position:fixed;inset:0;z-index:2100;background:#12243e66;display:grid;place-items:center;padding:16px}
.yc-defense-modal{background:#fff;width:min(510px,100%);border-radius:14px;padding:20px;box-shadow:0 16px 60px #10234b44;display:flex;flex-direction:column;gap:14px;color:#273a54;max-height:90vh;overflow-y:auto}
.yc-defense-modal-head{display:flex;align-items:center;justify-content:space-between}
.yc-defense-modal h3{font-size:18px;margin:0}
.yc-defense-modal-head button{border:0;background:transparent;font-size:25px;cursor:pointer;color:#789}
.yc-defense-modal p{font-size:13px;margin:0;line-height:1.7}
.yc-defense-modal label{display:grid;gap:7px;font-size:13px;font-weight:600}
.yc-defense-modal input:not([type=file]),.yc-defense-modal textarea{border:1px solid #dce3f0;border-radius:6px;padding:10px;width:100%;font:inherit;font-weight:400;color:#283b58;resize:vertical}
.yc-defense-modal input[type=file]{font-size:12px}
.yc-defense-file-tip{color:#467ce1}
.yc-defense-modal-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:8px}
.yc-defense-modal-actions button{border:1px solid #dbe4ef;background:white;padding:9px 16px;border-radius:6px;cursor:pointer;color:#64758c}
.yc-defense-modal-actions .primary{background:#3561fa;color:#fff;border-color:#3561fa}
.yc-defense-modal-actions .primary:disabled{background:#b8c8e8}
.yc-defense-photo-mask{position:fixed;inset:0;z-index:2200;background:#0a1123e8;display:flex;align-items:center;justify-content:center}
.yc-defense-photo-mask button{position:absolute;right:30px;top:20px;color:#fff;border:1px solid #fff8;background:transparent;border-radius:6px;padding:7px 12px;cursor:pointer}
.yc-defense-photo-mask img{max-width:90vw;max-height:90vh;object-fit:contain}
@media(max-width:1050px){.yc-defense-metrics{gap:9px}.yc-defense-grid{gap:10px}.yc-defense-metric{padding:15px}}
@media(max-width:750px){.yc-defense-workspace{overflow:auto;height:auto;padding:10px}.yc-defense-grid{grid-template-columns:1fr}.yc-defense-panel{overflow:visible}.yc-defense-metrics{grid-template-columns:1fr}.yc-defense-head-actions{flex-wrap:wrap}.yc-defense-hint{display:none}}
</style>
