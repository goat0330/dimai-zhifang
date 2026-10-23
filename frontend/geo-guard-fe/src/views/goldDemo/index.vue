<template>
  <main class="gold-page" :class="{ 'is-embedded': embedded }">
    <header v-if="!embedded" class="page-head">
      <div>
        <el-button text @click="router.push({ name: 'CockpitHome' })">← 返回驾驶舱</el-button>
        <p class="eyebrow">宜昌市地质灾害防治平台</p>
        <h1>双事件业务流程</h1>
      </div>
      <div class="head-tags">
        <el-tag effect="plain" type="primary">Gold 流程演示</el-tag>
        <el-tag effect="plain" type="warning">业务记录为模拟数据</el-tag>
      </div>
    </header>

    <header v-if="embedded" class="embedded-toolbar">
      <div>
        <p class="eyebrow">首页地图点位 · {{ scenarioLabel }}</p>
        <strong>{{ eventTitle }}</strong>
        <small>模拟业务记录；Dify 仅在你点击对应智能体按钮后调用。</small>
      </div>
      <div class="scenario-actions">
        <el-button v-if="savedRunId" :loading="pageLoading" @click="loadSaved">读取最近流程</el-button>
        <el-button v-if="run" :loading="refreshing" @click="refreshRun">刷新</el-button>
        <el-button type="primary" :loading="starting" @click="startRun">{{ run ? '新建一轮' : '启动流程' }}</el-button>
      </div>
    </header>

    <section v-if="!embedded" class="scenario-card">
      <div class="scenario-list">
        <button :class="{ selected: scenario === 'GOLD-01' }" @click="selectScenario('GOLD-01')">
          <span>GOLD-01 · 五峰</span><strong>现场巡查报灾</strong><small>上报、调查、研判与处置</small>
        </button>
        <button :class="{ selected: scenario === 'GOLD-02' }" @click="selectScenario('GOLD-02')">
          <span>GOLD-02 / GOLD-03 · 秭归</span><strong>监测告警与恢复跟踪</strong><small>恢复阶段追加到同一事件和任务链</small>
        </button>
      </div>
      <div class="scenario-actions">
        <el-button v-if="savedRunId && !run" @click="loadSaved">读取已保存流程</el-button>
        <el-button type="primary" :loading="starting" @click="startRun">{{ run ? '新建一次流程' : '启动演示流程' }}</el-button>
      </div>
      <p>页面只读取或写入 Gold 业务接口记录；Dify 调用仅由用户点击对应按钮触发。</p>
    </section>

    <section v-if="pageLoading" class="empty-state"><el-icon class="is-loading"><Loading /></el-icon> 正在读取已保存记录…</section>
    <section v-else-if="!run" class="empty-state">
      <h2>{{ loadError ? '流程记录暂时无法读取' : embedded ? '启动此地图点位的业务流程' : '选择场景，启动演示流程' }}</h2>
      <p>{{ loadError || '启动后会创建持久化 Gold 流程；刷新后可从当前链接或本机最近记录继续。' }}</p>
      <el-button v-if="loadError" @click="loadSaved">重试读取</el-button>
      <el-button v-else type="primary" :loading="starting" @click="startRun">启动 {{ scenario }} 流程</el-button>
    </section>

    <section v-else class="run-area">
      <header class="event-card">
        <div class="event-heading">
          <div>
            <div class="eyebrow">{{ scenarioLabel }} · {{ formatTime(event.occurred_at || event.discovery_time) }}</div>
            <h2>{{ eventTitle }}</h2>
            <p>{{ eventSummary }}</p>
          </div>
          <div class="event-tags">
            <el-tag :type="eventCompleted ? 'success' : 'warning'">{{ eventCompleted ? '已完成' : eventStatus }}</el-tag>
            <el-tag effect="plain">{{ event.is_simulated === false ? 'P6候选数据' : 'Gold演示事件' }}</el-tag>
          </div>
        </div>
        <div class="event-facts">
          <div><span>行政区</span><strong>{{ event.admin_area || event.risk_info?.admin_area || '—' }}</strong></div>
          <div><span>事件来源</span><strong>{{ sourceLabel(event.source_kind, event.data_source) }}</strong></div>
          <div><span>空间关联</span><strong>{{ p6.mapping_status || event.spatial_ref_status || '—' }}</strong></div>
          <div><span>事件编号</span><strong class="mono">{{ run.runtime_event_id || event.event_id }}</strong></div>
        </div>
        <div class="run-meta">
          <span>Run {{ run.run_id }}</span><span>Trace {{ run.trace_id || event.trace_id || '—' }}</span>
          <span>引擎 {{ engineLabel(run.execution_engine) }}</span><span>{{ recordCount }} 条持久化记录</span>
        </div>
      </header>

      <div class="flow-strip">
        <div v-for="(step, index) in flow" :key="step.key" :class="{ done: step.done, current: activePane === step.key }">
          <i>{{ step.done ? '✓' : index + 1 }}</i><span>{{ step.label }}</span>
        </div>
      </div>

      <div class="workspace">
        <section class="main-panel">
          <el-tabs v-model="activePane">
            <el-tab-pane label="现场与上报" name="field">
              <section class="section">
                <div class="section-head"><div><h3>现场信息与报灾记录</h3><p>从已保存事件、现场调查和图片引用中读取。</p></div><el-tag effect="plain">{{ engineLabel(field.engine || discovery.execution_engine || 'local') }}</el-tag></div>
                <div class="two-col">
                  <article class="info-card">
                    <h4>报灾信息</h4>
                    <dl>
                      <div><dt>内容</dt><dd>{{ field.summary || field.narrative || discovery.narrative || event.summary || '—' }}</dd></div>
                      <div><dt>发现时间</dt><dd>{{ formatTime(field.occurred_at || discovery.discovery_time || event.occurred_at) }}</dd></div>
                      <div><dt>报告人</dt><dd>{{ discovery.reporter_name || discovery.reporter_id || '—' }}</dd></div>
                      <div><dt>来源记录</dt><dd class="mono">{{ field.data_source || discovery.data_source || event.data_source || '—' }}</dd></div>
                    </dl>
                  </article>
                  <article class="info-card">
                    <h4>现场调查</h4>
                    <dl>
                      <div><dt>调查结论</dt><dd>{{ investigation.conclusion || '尚未形成调查结论' }}</dd></div>
                      <div><dt>调查时间</dt><dd>{{ formatTime(investigation.investigation_time?.start || investigation.created_at) }}</dd></div>
                      <div><dt>待核实事项</dt><dd>{{ listText(investigation.missing_fields || event.missing_fields) }}</dd></div>
                      <div><dt>数据来源</dt><dd>{{ investigation.data_source || '—' }}</dd></div>
                    </dl>
                  </article>
                </div>
                <article class="info-card">
                  <div class="section-head"><div><h4>现场图片与识别状态</h4><p>已保存 {{ photoRefs.length }} 条图片引用</p></div><el-tag :type="visionPending ? 'warning' : 'info'">{{ statusLabel(visionStatus) }}</el-tag></div>
                  <div v-for="(photo, index) in photoRefs" :key="photo.path || index" class="photo-ref">
                    <span>图</span><div><strong>{{ photoName(photo) }}</strong><small>{{ photo.evidence_scope || photo.media_kind || '图片引用' }}</small></div>
                  </div>
                  <p v-if="visionPending" class="notice">图片上传能力未启用，照片仅作为场景资料展示，尚无视觉模型识别结论。</p>
                  <div v-if="scenario === 'GOLD-01'" class="action-row">
                    <el-button type="primary" plain :loading="pending === 'a2'" :disabled="Boolean(executionFor('A2'))" @click="doA2">
                      {{ executionFor('A2') ? 'A2 已执行' : '调用 Dify 执行 A2 图像研判' }}
                    </el-button><small>仅在点击后调用，不把图片引用显示为识别结果。</small>
                  </div>
                </article>
              </section>
            </el-tab-pane>

            <el-tab-pane label="监测与风险" name="monitor">
              <section class="section">
                <div class="section-head"><div><h3>监测记录与 P6 风险</h3><p>等级来自关联斜坡单元记录；静态易发性与动态风险分别展示。</p></div><el-tag type="primary" effect="plain">{{ p6.snapshot_id || '无P6时片' }}</el-tag></div>
                <div v-if="scenario === 'GOLD-02'" class="stage-switch">
                  <span>同一事件的监测阶段</span>
                  <el-radio-group v-model="activeStage" size="small">
                    <el-radio-button label="GOLD-02">GOLD-02 监测阶段</el-radio-button>
                    <el-radio-button label="GOLD-03">GOLD-03 恢复阶段</el-radio-button>
                  </el-radio-group>
                  <small>共用事件编号与同一组任务</small>
                </div>
                <div class="two-col">
                  <article class="info-card">
                    <h4>{{ scenario === 'GOLD-02' ? activeStage + ' 监测记录' : '现场与监测来源' }}</h4>
                    <dl>
                      <div><dt>设备</dt><dd>{{ device.device_name || device.device_id || event.device_id || '—' }}</dd></div>
                      <div><dt>监测点</dt><dd>{{ device.monitor_point_id || event.monitor_point_id || discovery.monitor_point_id || '—' }}</dd></div>
                      <div><dt>监测序列</dt><dd class="mono">{{ event.monitoring_series_id || device.monitoring_series_id || '—' }}</dd></div>
                      <div><dt>阶段状态</dt><dd>{{ statusLabel(activeAssessment.status || activeAssessment.event_status || 'not_run') }}</dd></div>
                      <div><dt>来源</dt><dd>{{ activeAssessment.data_source || event.monitoring?.data_source || device.data_source || '—' }}</dd></div>
                    </dl>
                    <details v-if="activeMonitoring"><summary>查看监测指标</summary><pre>{{ pretty(activeMonitoring) }}</pre></details>
                  </article>
                  <article class="info-card p6-card">
                    <div class="section-head"><div><h4>斜坡单元评价</h4><p class="mono">{{ p6.slope_unit_id || event.p6_slope_unit_id || event.slope_unit_id || '未关联斜坡单元' }}</p></div><el-tag type="warning">{{ p6.mapping_status || '关联状态待核验' }}</el-tag></div>
                    <div class="grade-grid">
                      <div v-for="item in p6Metrics" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.grade }}</strong><small>{{ item.score }}</small></div>
                    </div>
                    <p v-if="p6.model_rainfall" class="rain-line">{{ p6.source_kind || 'P6记录' }} · 过去24小时 {{ numberOrDash(p6.model_rainfall.past24h_mm) }} mm</p>
                    <details v-if="p6.V"><summary>查看资产易损性系数</summary><div class="asset-values"><span v-for="item in vMetrics" :key="item.key">{{ item.label }} {{ item.value }}</span></div></details>
                  </article>
                </div>
                <div v-if="scenario === 'GOLD-02'" class="action-row">
                  <el-button v-if="activeStage === 'GOLD-02' && !hasRecovery" :loading="pending === 'recovery'" @click="doRecovery">追加 GOLD-03 恢复阶段</el-button>
                  <el-button type="primary" :loading="pending === 'a3'" :disabled="Boolean(executionFor('A3', activeStage)) || (activeStage === 'GOLD-03' && !hasRecovery)" @click="doA3">
                    {{ executionFor('A3', activeStage) ? activeStage + ' A3 已执行' : '调用 Dify 执行 ' + activeStage + ' A3 监测研判' }}
                  </el-button><small>A3仅在用户点击时调用，执行结果保存到当前事件。</small>
                </div>
              </section>
            </el-tab-pane>

            <el-tab-pane label="决策与任务" name="tasks">
              <section class="section">
                <div class="section-head"><div><h3>A4 决策、处置方案与任务</h3><p>状态来自已保存的决策、方案审核、任务、反馈和复核记录。</p></div><el-tag :type="planApproved ? 'success' : 'warning'">{{ planApproved ? '方案已审核' : '方案待审核' }}</el-tag></div>
                <article class="info-card">
                  <div class="section-head"><h4>风险分析与处置建议</h4><small v-if="latestA4">{{ engineLabel(latestA4.execution_engine) }} · {{ statusLabel(latestA4.status) }}</small></div>
                  <p>{{ decisionText }}</p>
                  <details v-if="decision.disposal_plan || decision.task_proposal"><summary>查看 A4 方案记录</summary><pre>{{ pretty({ disposal_plan: decision.disposal_plan, task_proposal: decision.task_proposal }) }}</pre></details>
                  <div class="action-row">
                    <el-button type="primary" plain :loading="pending === 'a4'" :disabled="Boolean(latestA4?.status === 'completed')" @click="doA4">调用 Dify 执行 A4 决策研判</el-button>
                    <el-button :loading="pending === 'plan'" :disabled="!latestA4 || Boolean(run.plan_review_id)" @click="doPlanReview">
                      {{ planApproved ? '方案审核已完成' : '回放 Gold 方案审核并生成任务' }}
                    </el-button>
                  </div>
                  <p class="notice">A4文本方案需经过方案审核后才会生成任务；Gold审核为演示回放。</p>
                </article>
                <div class="task-head">
                  <div><h4>处置任务与执行反馈</h4><p>{{ tasks.length }} 条任务 · 当前反馈阶段 {{ scenario === 'GOLD-01' ? 'GOLD-01' : activeStage }}</p></div>
                  <el-button :disabled="!planApproved || (activeStage === 'GOLD-03' && !hasRecovery)" :loading="pending === 'feedback'" @click="doFeedback">
                    回放 {{ scenario === 'GOLD-01' ? '现场' : activeStage }} Gold 反馈
                  </el-button>
                </div>
                <div v-if="tasks.length" class="task-list">
                  <article v-for="(task, index) in tasks" :key="task.task_id || task.fixture_task_key" class="task-card">
                    <div class="task-top"><strong><i>{{ String(index + 1).padStart(2, '0') }}</i>{{ task.action?.title || task.title || ('处置任务 ' + (index + 1)) }}</strong><el-tag :type="statusTone(task.status)">{{ statusLabel(task.status) }}</el-tag></div>
                    <p>{{ task.action?.action || task.action || '—' }}</p>
                    <div class="task-meta"><span>责任人：{{ task.action?.person || task.assignee_id || '—' }}</span><span>地点：{{ task.action?.location || '—' }}</span><span>期限：{{ formatTime(task.action?.due_at || task.due_at) }}</span></div>
                    <div v-for="feedback in taskFeedbacks(task)" :key="feedback.feedback_id" class="task-record">
                      <small>执行反馈 · {{ formatTime(feedback.feedback_time) }} · {{ statusLabel(feedback.status) }}</small>
                      <span>{{ feedback.actual_actions || feedback.field_description || '已保存反馈记录' }}</span>
                      <small>来源：{{ feedback.data_source || engineLabel(feedback.execution_engine) }}</small>
                    </div>
                    <div v-if="taskReview(task)" class="task-record reviewed">
                      <small>任务复核 · {{ formatTime(taskReview(task).review_time) }}</small><span>{{ taskReview(task).review_comment || statusLabel(taskReview(task).status) }}</span>
                      <small>{{ engineLabel(taskReview(task).execution_engine) }} · {{ statusLabel(taskReview(task).status) }}</small>
                    </div>
                    <div v-if="!taskFeedbacks(task).length && !taskReview(task)" class="task-empty">暂无已保存的反馈与复核记录</div>
                    <div class="task-foot"><code>{{ task.task_id }}</code><el-button v-if="!taskReview(task)" size="small" :disabled="!planApproved || !taskFeedbacks(task).length || (scenario === 'GOLD-02' && !hasRecovery)" :loading="pending === ('task:' + task.fixture_task_key)" @click="doTaskReview(task)">回放 Gold 任务复核</el-button><small v-else>复核已记录</small></div>
                  </article>
                </div>
                <div v-else class="inline-empty">方案审核通过后，处置任务将从接口记录中显示。</div>
              </section>
            </el-tab-pane>

            <el-tab-pane label="报告与回查" name="reports">
              <section class="section">
                <div class="section-head"><div><h3>调查、处置与复盘报告</h3><p>报告正文、审核状态与 DOCX 均读取当前 run 的记录。</p></div><el-tag effect="plain">{{ reports.length }} 份报告</el-tag></div>
                <div class="action-row report-actions">
                  <el-button type="primary" plain :loading="pending === 'a5-investigation'" :disabled="hasInvestigationReport" @click="doA5Investigation">调用 Dify 执行 A5 调查报告</el-button>
                  <el-button :loading="pending === 'retrospective'" :disabled="!canGenerateReport || Boolean(finalReport)" @click="doRetrospective(false)">生成复盘报告（本地事实模板）</el-button>
                  <el-button v-if="!finalReport" type="primary" :loading="pending === 'retrospective-dify'" :disabled="!canGenerateReport" @click="doRetrospective(true)">调用 Dify 生成复盘报告</el-button>
                  <el-button v-if="finalReport && !finalReportApproved" type="success" :loading="pending === 'final-review'" @click="doFinalReview">回放最终报告审核</el-button>
                  <el-tag v-if="eventCompleted" type="success">最终报告审核通过，事件已完成</el-tag>
                </div>
                <div v-if="reports.length" class="report-list">
                  <article v-for="report in reports" :key="report.report_id" class="report-row">
                    <div class="report-file">文</div><div class="report-copy"><strong>{{ report.title || reportTypeLabel(report.report_type) }}</strong><span>{{ reportTypeLabel(report.report_type) }} · {{ statusLabel(report.status) }}<template v-if="report.review_status"> · {{ statusLabel(report.review_status) }}</template></span><small>{{ engineLabel(report.execution_engine) }} · {{ statusLabel(report.generation_status || report.docx_status || 'recorded') }}</small></div>
                    <el-button link type="primary" @click="openReport(report)">预览</el-button>
                    <el-button link type="primary" :loading="pending === ('docx:' + report.report_id)" @click="downloadReport(report)">下载 DOCX</el-button>
                  </article>
                </div>
                <div v-else class="inline-empty">当前 run 尚未生成报告。</div>
                <article class="info-card qa-card">
                  <div class="section-head"><div><h4>A1 已审批报告回查</h4><p>按报告编号精确查询；结果以业务接口返回为准。</p></div><el-tag effect="plain">点击后查询</el-tag></div>
                  <div class="qa-controls"><el-input v-model="qaQuery" placeholder="输入报告编号，或留空回查当前报告" clearable /><el-button type="primary" :loading="pending === 'qa'" :disabled="!reports.length" @click="doQa">回查报告</el-button></div>
                  <pre v-if="qaResult" class="json-block">{{ pretty(qaResult) }}</pre>
                </article>
              </section>
            </el-tab-pane>
          </el-tabs>
        </section>

        <aside class="trace-panel">
          <div class="section-head"><div><h3>执行记录</h3><p>引擎、状态和输出来自已保存记录</p></div><el-button text :loading="refreshing" @click="refreshRun">刷新</el-button></div>
          <div class="counts"><div><strong>{{ tasks.length }}</strong><span>任务</span></div><div><strong>{{ feedbacks.length }}</strong><span>反馈</span></div><div><strong>{{ reviews.length }}</strong><span>复核</span></div><div><strong>{{ reports.length }}</strong><span>报告</span></div></div>
          <div class="trace-list">
            <article v-for="(item, index) in executionItems" :key="item.record_id || index" class="trace-row">
              <i :class="statusTone(item.status)"></i><div><strong>{{ item.agent_id || item.record_type || '业务记录' }}<small v-if="item.stage_id"> · {{ item.stage_id }}</small></strong>
                <el-tag size="small" effect="plain">{{ engineLabel(item.execution_engine) }}</el-tag>
                <p>{{ statusLabel(item.status) }}<template v-if="item.output_status"> · {{ outputLabel(item.output_status) }}</template></p>
                <small>Trace {{ item.trace_id || run.trace_id || '—' }}</small>
              </div>
            </article>
            <div v-if="!executionItems.length" class="inline-empty">流程执行后，记录会显示在这里。</div>
          </div>
          <p v-if="loadError" class="error-text">{{ loadError }}</p>
        </aside>
      </div>
    </section>

    <el-dialog v-model="previewVisible" :title="selectedReport?.title || '报告预览'" width="760px">
      <article class="report-preview" v-dompurify-html="previewHtml"></article>
      <template #footer><el-button @click="previewVisible = false">关闭</el-button><el-button v-if="selectedReport" type="primary" @click="downloadReport(selectedReport)">下载 DOCX</el-button></template>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import { useRoute, useRouter } from 'vue-router'
import {
  createGoldRetrospective, downloadGoldReport, executeGoldA2, executeGoldA3,
  executeGoldA4, executeGoldA5Investigation, executeGoldRecovery, queryGold,
  readGoldRun, replayGoldFeedback, reviewGoldFinalReport, reviewGoldPlan,
  reviewGoldTask, startGoldRun,
} from '@/api/yichangGold.js'

defineOptions({ name: 'YichangGoldDemo' })
const props = defineProps({
  embedded: { type: Boolean, default: false },
  initialScenario: { type: String, default: 'GOLD-01' },
  initialRunId: { type: String, default: '' },
  autoStartOnOpen: { type: Boolean, default: false },
})
const STORAGE = 'geo-guard:yichang-gold:'
const LABELS = {
  recorded: '已记录', completed: '已完成', accepted: '已通过', accepted_with_followup: '通过，需跟进',
  submitted_pending_task_review: '待任务复核', awaiting_recovery_stage: '待恢复监测',
  awaiting_task_review: '待任务复核', awaiting_final_report_review: '待最终报告审核',
  awaiting_final_report: '待生成复盘报告', task_execution_in_progress: '处置进行中',
  draft_unreviewed: '待审核', approved_for_gold_replay: '演示审核通过', approved: '已批准',
  not_reviewed: '未审核', unsupported_output: '未形成可用报告内容', execution_failed: '执行失败',
  error: '执行失败', pending_visual_model: '待图像识别', deferred_to_phase2: '图片识别未启用',
  image_input_not_enabled: '图片上传未启用', text_only_review_required: '文本方案待审核',
  not_run: '尚未执行', triggered: '已触发', recovery_observed: '恢复阶段已记录', superseded: '已替代',
}
const router = useRouter()
const route = useRoute()
const md = new MarkdownIt({ html: false, breaks: true, linkify: true })
const scenario = ref('GOLD-01')
const activeStage = ref('GOLD-01')
const activePane = ref('field')
const snapshot = ref(null)
const pageLoading = ref(false)
const starting = ref(false)
const refreshing = ref(false)
const pending = ref('')
const loadError = ref('')
const savedRunId = ref('')
const previewVisible = ref(false)
const selectedReport = ref(null)
const qaQuery = ref('')
const qaResult = ref(null)
let objectUrl = ''

const run = computed(() => snapshot.value?.run || null)
const eventRow = computed(() => snapshot.value?.event || {})
const event = computed(() => eventRow.value?.payload || eventRow.value || {})
const groups = computed(() => snapshot.value?.records || {})
function list(type) {
  const rows = groups.value?.[type]
  return Array.isArray(rows) ? rows.map((row) => row?.payload || row) : []
}
const tasks = computed(() => list('task'))
const feedbacks = computed(() => list('feedback'))
const reviews = computed(() => list('task_review'))
const reports = computed(() => list('report'))
const approvals = computed(() => list('approval'))
const executions = computed(() => list('dify_execution'))
const discovery = computed(() => list('discovery').at(-1) || {})
const field = computed(() => list('field_report').at(-1) || event.value.field_report || {})
const investigation = computed(() => list('investigation').at(-1) || event.value.field_investigation_record?.gold_fixture_record || {})
const device = computed(() => list('device').at(-1) || event.value.device || {})
const decision = computed(() => list('decision').at(-1) || {})
const activeAssessment = computed(() => list('monitoring_assessment').find((item) => item.stage_id === activeStage.value) || {})
const activeMonitoring = computed(() => activeAssessment.value.monitoring || activeAssessment.value.p6_dynamic_monitoring || event.value.monitoring || null)
const p6 = computed(() => event.value.p6_fixture_reference || activeAssessment.value.p6_dynamic_snapshot || event.value.p6_dynamic_snapshot || event.value.p6_snapshot || {})
const photoRefs = computed(() => field.value.photo_refs || field.value.field_report?.photo_refs || discovery.value.image_refs || event.value.field_report?.photo_refs || [])
const vision = computed(() => event.value.vision_execution || executionFor('A2') || {})
const visionStatus = computed(() => vision.value.analysis_status || vision.value.status || event.value.image_analysis_status || 'not_run')
const visionPending = computed(() => ['deferred_to_phase2', 'pending_visual_model', 'image_input_not_enabled'].includes(visionStatus.value))
const hasRecovery = computed(() => list('monitoring_assessment').some((item) => item.stage_id === 'GOLD-03'))
const latestA4 = computed(() => executionFor('A4'))
const planApproved = computed(() => Boolean(run.value?.plan_review_id || approvals.value.some((item) => (
  item.approval_type === 'plan' || item.plan_fixture_key || item.decision === 'approved_for_gold_replay'
))))
const finalReport = computed(() => reports.value.filter((item) => item.report_type === 'retrospective' && item.status !== 'superseded').at(-1) || null)
const finalReportApproved = computed(() => finalReport.value?.status === 'approved' && finalReport.value?.review_status === 'approved')
const eventCompleted = computed(() => (
  ['completed'].includes(event.value.status || event.value.event_status)
  && finalReportApproved.value
  && (!event.value.completed_report_id || event.value.completed_report_id === finalReport.value?.report_id)
))
const eventStatus = computed(() => {
  if ((event.value.status === 'completed' || event.value.event_status === 'completed') && !eventCompleted.value) return '待最终报告审核'
  return statusLabel(event.value.status || event.value.event_status || run.value?.status)
})
const canGenerateReport = computed(() => tasks.value.length > 0 && tasks.value.every((task) => Boolean(taskReview(task))) && (scenario.value !== 'GOLD-02' || hasRecovery.value))
const hasInvestigationReport = computed(() => reports.value.some((item) => item.report_type === 'investigation'))
const p6Metrics = computed(() => {
  const e = p6.value.E?.total || p6.value.E || {}
  const r = p6.value.R_dynamic || p6.value.R || {}
  return [
    { label: '静态易发性', grade: p6.value.S?.grade || '—', score: numberOrDash(p6.value.S?.score) },
    { label: '动态危险性', grade: p6.value.H_dynamic?.grade || '—', score: numberOrDash(p6.value.H_dynamic?.score) },
    { label: '暴露度', grade: e.grade || '—', score: numberOrDash(e.score) },
    { label: '动态综合风险', grade: r.grade || '—', score: numberOrDash(r.score) },
    { label: '预测风险', grade: p6.value.R_forecast?.grade || '—', score: numberOrDash(p6.value.R_forecast?.score) },
  ]
})
const vMetrics = computed(() => Object.entries(p6.value.V || {}).map(([key, value]) => ({
  key, label: ({ population: '人口', highway: '高速/快速路', national_provincial: '国省干道', county_township: '县乡道路', village_other: '村道及其他' })[key] || key,
  value: value?.coefficient ?? value?.score ?? '—',
})))
const decisionText = computed(() => {
  const value = decision.value.recommendation
  if (typeof value === 'string') return value
  return value?.summary || decision.value.disposal_plan?.summary || (decision.value.decision_status ? statusLabel(decision.value.decision_status) : 'A4 决策记录尚未生成。')
})
const eventTitle = computed(() => event.value.event_name || event.value.title || event.value.risk_info?.hazard_point_name || device.value.device_name || (scenario.value === 'GOLD-01' ? '五峰现场巡查报灾事件' : '秭归监测告警事件'))
const eventSummary = computed(() => event.value.summary || event.value.monitoring?.trigger_reason || event.value.risk_info?.description || event.value.description || '事件描述以已保存的现场与监测记录为准。')
const scenarioLabel = computed(() => scenario.value === 'GOLD-01' ? 'GOLD-01 · 五峰现场巡查' : 'GOLD-02 / GOLD-03 · 秭归监测与恢复')
const recordCount = computed(() => Object.values(groups.value).reduce((n, value) => n + (Array.isArray(value) ? value.length : 0), 0))
const flow = computed(() => [
  { key: 'field', label: '现场上报', done: Boolean(field.value.record_id || discovery.value.discovery_id) },
  { key: 'monitor', label: '监测与风险', done: Boolean(p6.value.slope_unit_id || list('monitoring_assessment').length) },
  { key: 'tasks', label: '决策与任务', done: tasks.value.length > 0 },
  { key: 'reports', label: '报告审核', done: finalReportApproved.value },
])
const executionItems = computed(() => [
  ...executions.value.map((item) => ({ ...item, record_type: '智能体执行' })),
  ...list('rag_retrieval').map((item) => ({ ...item, record_type: '报告检索' })),
  ...approvals.value.map((item) => ({ ...item, record_type: '审核记录', execution_engine: item.execution_engine || 'local' })),
].slice(-12).reverse())
const previewHtml = computed(() => md.render(selectedReport.value?.report_text || selectedReport.value?.sections?.runtime_business_markdown || '当前报告记录没有可预览的正文。'))

function statusLabel(value) { return value ? (LABELS[value] || String(value).replaceAll('_', ' ')) : '待处理' }
function statusTone(value) {
  if (['completed', 'accepted', 'approved', 'approved_for_gold_replay', 'recorded', 'recovery_observed'].includes(value)) return 'success'
  if (['error', 'execution_failed', 'rejected'].includes(value)) return 'danger'
  if (['awaiting_final_report_review', 'awaiting_task_review', 'submitted_pending_task_review', 'pending_visual_model', 'deferred_to_phase2'].includes(value)) return 'warning'
  return 'info'
}
function engineLabel(value) { return value === 'dify' ? 'Dify' : value === 'local' ? '本地 Gold' : value || '未记录' }
function sourceLabel(kind, source) { return kind === 'SIMULATED' || String(source || '').includes('local_gold_fixture') ? 'Gold 场景记录' : source || kind || '—' }
function reportTypeLabel(value) { return ({ investigation: '调查报告', disposal_opinion: '处置意见书', retrospective: '处置复盘报告', final: '最终报告' })[value] || value || '业务报告' }
function outputLabel(value) { return typeof value === 'string' ? statusLabel(value) : value && typeof value === 'object' ? Object.entries(value).map(([k, v]) => k + '：' + statusLabel(v)).join('；') : '' }
function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
function numberOrDash(value) { return value === null || value === undefined || value === '' ? '—' : Number(value).toFixed(2) }
function listText(value) { return Array.isArray(value) ? value.join('；') || '—' : value || '—' }
function pretty(value) { try { return JSON.stringify(value, null, 2) } catch (_) { return String(value || '—') } }
function photoName(photo) { const path = typeof photo === 'string' ? photo : photo?.path || photo?.filename; return path ? String(path).split(/[\\/]/).at(-1) : '现场图片引用' }
function executionFor(agent, stage) { return executions.value.filter((item) => item.agent_id === agent && (!stage || item.stage_id === stage)).at(-1) || null }
function taskReview(task) { return reviews.value.find((item) => item.task_id === task.task_id || item.task_fixture_key === task.fixture_task_key) || null }
function feedbackBelongsToStage(item, stage) {
  if (scenario.value === 'GOLD-01') return true
  return [item.stage_id, item.feedback_fixture_key, item.fixture_feedback_key, item.data_source].filter(Boolean).join(' ').includes(stage)
}
function taskFeedbacks(task) { return feedbacks.value.filter((item) => item.task_id === task.task_id && feedbackBelongsToStage(item, activeStage.value)) }

function routeState(runId, scenarioId, stage) {
  if (props.embedded) return
  const query = { scenario: scenarioId }
  if (runId) query.run_id = runId
  if (scenarioId === 'GOLD-02') query.stage = stage
  router.replace({ name: 'YichangGoldDemo', query })
}
async function readRun(runId) {
  if (!runId) return
  pageLoading.value = true
  loadError.value = ''
  try {
    snapshot.value = await readGoldRun(runId)
    scenario.value = snapshot.value.run?.scenario_id === 'GOLD-02' ? 'GOLD-02' : 'GOLD-01'
    activeStage.value = scenario.value === 'GOLD-02' && !props.embedded && ['GOLD-02', 'GOLD-03'].includes(String(route.query.stage)) ? String(route.query.stage) : scenario.value
    localStorage.setItem(STORAGE + 'run:' + scenario.value, runId)
    localStorage.setItem(STORAGE + 'last-scenario', scenario.value)
    savedRunId.value = runId
    routeState(runId, scenario.value, activeStage.value)
  } catch (error) { loadError.value = error.message || '读取流程失败' }
  finally { pageLoading.value = false }
}
async function selectScenario(value) {
  scenario.value = value
  activeStage.value = value === 'GOLD-01' ? 'GOLD-01' : 'GOLD-02'
  activePane.value = 'field'
  snapshot.value = null
  qaResult.value = null
  loadError.value = ''
  savedRunId.value = localStorage.getItem(STORAGE + 'run:' + value) || ''
  if (savedRunId.value) await readRun(savedRunId.value)
  else routeState('', value, activeStage.value)
}
async function loadSaved() {
  const id = savedRunId.value || localStorage.getItem(STORAGE + 'run:' + scenario.value)
  if (id) await readRun(id)
}
async function startRun() {
  starting.value = true
  loadError.value = ''
  try {
    const result = await startGoldRun(scenario.value)
    const id = result.run?.run_id || result.run_id
    if (!id) throw new Error('启动接口没有返回 run_id')
    localStorage.setItem(STORAGE + 'run:' + scenario.value, id)
    localStorage.setItem(STORAGE + 'last-scenario', scenario.value)
    await readRun(id)
    activePane.value = 'field'
    ElMessage.success('演示流程已启动并保存')
  } catch (error) { loadError.value = error.message || '启动流程失败'; ElMessage.error(loadError.value) }
  finally { starting.value = false }
}
async function refreshRun() {
  if (!run.value?.run_id) return
  refreshing.value = true
  try { snapshot.value = await readGoldRun(run.value.run_id); loadError.value = '' }
  catch (error) { loadError.value = error.message || '刷新流程失败'; ElMessage.error(loadError.value) }
  finally { refreshing.value = false }
}
async function mutate(key, action, message) {
  const id = run.value?.run_id
  if (!id) return
  pending.value = key
  loadError.value = ''
  try { await action(); snapshot.value = await readGoldRun(id); if (message) ElMessage.success(message) }
  catch (error) { loadError.value = error.message || '操作失败'; ElMessage.error(loadError.value) }
  finally { pending.value = '' }
}
function doA2() { return mutate('a2', () => executeGoldA2(run.value.run_id), 'A2执行结果已保存') }
function doA3() { return mutate('a3', () => executeGoldA3(run.value.run_id, activeStage.value), activeStage.value + ' A3结果已保存') }
function doA4() { return mutate('a4', () => executeGoldA4(run.value.run_id), 'A4执行结果已保存') }
function doPlanReview() { return mutate('plan', () => reviewGoldPlan(run.value.run_id), 'Gold方案审核记录已保存') }
function doFeedback() { const stage = scenario.value === 'GOLD-01' ? 'GOLD-01' : activeStage.value; return mutate('feedback', () => replayGoldFeedback(run.value.run_id, stage), 'Gold反馈记录已保存') }
function doRecovery() { return mutate('recovery', () => executeGoldRecovery(run.value.run_id), 'GOLD-03已追加到同一事件') }
function doTaskReview(task) { return mutate('task:' + task.fixture_task_key, () => reviewGoldTask(run.value.run_id, task.fixture_task_key), '任务复核结果已保存') }
function doA5Investigation() { return mutate('a5-investigation', () => executeGoldA5Investigation(run.value.run_id), 'A5调查报告结果已保存') }
function doRetrospective(useDify) {
  const key = useDify ? 'retrospective-dify' : 'retrospective'
  return mutate(key, () => createGoldRetrospective(run.value.run_id, useDify), useDify ? 'Dify报告执行记录已保存' : '本地事实模板报告已保存')
}
function doFinalReview() { return mutate('final-review', () => reviewGoldFinalReport(run.value.run_id), '最终报告审核记录已保存') }
async function doQa() {
  const report = finalReport.value || reports.value.find((item) => item.review_status === 'approved') || reports.value.at(-1)
  const query = qaQuery.value.trim() || (report?.report_id ? '回查报告 ' + report.report_id : '')
  if (!query) return
  pending.value = 'qa'
  try { qaResult.value = await queryGold(query) }
  catch (error) { loadError.value = error.message || '报告回查失败'; ElMessage.error(loadError.value) }
  finally { pending.value = '' }
}
function openReport(report) { selectedReport.value = report; previewVisible.value = true }
async function downloadReport(report) {
  if (!report?.report_id || !run.value?.run_id) return
  pending.value = 'docx:' + report.report_id
  try {
    const blob = await downloadGoldReport(run.value.run_id, report.report_id)
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    objectUrl = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = report.docx_file_name || (report.title || reportTypeLabel(report.report_type)) + '.docx'
    anchor.click()
    ElMessage.success('DOCX已下载')
    previewVisible.value = false
    await refreshRun()
  } catch (error) { loadError.value = error.message || 'DOCX下载失败'; ElMessage.error(loadError.value) }
  finally { pending.value = '' }
}
onMounted(async () => {
  if (props.embedded) {
    scenario.value = props.initialScenario === 'GOLD-02' ? 'GOLD-02' : 'GOLD-01'
    activeStage.value = scenario.value === 'GOLD-02' ? 'GOLD-02' : 'GOLD-01'
    const requestedRunId = props.initialRunId || localStorage.getItem(STORAGE + 'run:' + scenario.value) || ''
    if (props.autoStartOnOpen) await startRun()
    else if (requestedRunId) await readRun(requestedRunId)
    return
  }
  const queryScenario = ['GOLD-01', 'GOLD-02'].includes(String(route.query.scenario)) ? String(route.query.scenario) : ''
  const storedScenario = localStorage.getItem(STORAGE + 'last-scenario')
  scenario.value = queryScenario || (['GOLD-01', 'GOLD-02'].includes(storedScenario) ? storedScenario : 'GOLD-01')
  savedRunId.value = localStorage.getItem(STORAGE + 'run:' + scenario.value) || ''
  const queryRunId = String(route.query.run_id || '')
  if (queryRunId) await readRun(queryRunId)
  else if (savedRunId.value) await readRun(savedRunId.value)
  else routeState('', scenario.value, scenario.value === 'GOLD-01' ? 'GOLD-01' : 'GOLD-02')
})
onBeforeUnmount(() => { if (objectUrl) URL.revokeObjectURL(objectUrl) })
</script>

<style lang="less" scoped>
.gold-page { height: 100%; min-height: 0; overflow: auto; padding: 18px 20px 24px; box-sizing: border-box; color: #222527; }
.gold-page.is-embedded { padding: 12px 14px 18px; }
.page-head, .head-tags, .scenario-list, .scenario-actions, .event-heading, .event-tags, .event-facts, .run-meta, .flow-strip, .section-head, .action-row, .task-top, .task-meta, .task-foot, .report-row, .qa-controls, .trace-row { display: flex; align-items: center; }
.embedded-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 8px 2px 12px; }
.embedded-toolbar > div:first-child { min-width: 0; display: grid; gap: 4px; }
.embedded-toolbar strong { overflow: hidden; color: #222527; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.embedded-toolbar small { color: #9096a2; font-size: 10px; }
.page-head { justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.page-head h1 { margin: 2px 0 0; font-size: 22px; font-weight: 800; }
.eyebrow { margin: 4px 0; color: #617185; font-size: 12px; }
.head-tags { gap: 8px; flex-wrap: wrap; }
.scenario-card, .event-card, .main-panel, .trace-panel, .empty-state { border: 1px solid #e3eaf2; border-radius: 10px; background: #fff; box-shadow: 0 2px 8px rgba(24,54,92,.04); }
.scenario-card { padding: 13px 15px 9px; margin-bottom: 11px; }
.scenario-card > p { margin: 8px 1px 0; color: #9096a2; font-size: 11px; }
.scenario-list { gap: 9px; flex: 1; }
.scenario-list button { min-width: 220px; flex: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 10px 13px; text-align: left; background: #f7faff; border: 1px solid #e3eaf2; border-radius: 8px; cursor: pointer; }
.scenario-list button.selected, .scenario-list button:hover { border-color: #007bff; background: #eff6ff; }
.scenario-list button span { color: #007bff; font-size: 11px; font-weight: 700; }
.scenario-list button strong { color: #222527; font-size: 14px; }
.scenario-list button small, .scenario-actions .el-button + .el-button { color: #617185; font-size: 11px; }
.scenario-card { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 8px 14px; }
.scenario-list { grid-column: 1 / 2; grid-row: 1; }
.scenario-actions { grid-column: 2; grid-row: 1; justify-content: flex-end; gap: 8px; }
.scenario-card > p { grid-column: 1 / -1; grid-row: 2; }
.empty-state { min-height: 190px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 22px; text-align: center; color: #617185; }
.empty-state h2 { margin: 0; color: #222527; font-size: 18px; }
.empty-state p { margin: 0 0 6px; }
.run-area { min-height: 0; }
.event-card { padding: 15px 17px 10px; margin-bottom: 10px; }
.event-heading { align-items: flex-start; justify-content: space-between; gap: 18px; }
.event-heading h2 { margin: 4px 0; font-size: 18px; }
.event-heading p { margin: 0; color: #617185; font-size: 12px; line-height: 1.5; }
.event-tags { gap: 7px; flex-wrap: wrap; justify-content: flex-end; }
.event-facts { gap: 0; margin-top: 12px; border-top: 1px solid #edf0f4; }
.event-facts > div { flex: 1; min-width: 0; padding: 8px 12px 3px 0; }
.event-facts span, .event-facts strong { display: block; }
.event-facts span { color: #9096a2; font-size: 10px; }
.event-facts strong { margin-top: 3px; overflow: hidden; color: #383c41; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.run-meta { gap: 12px; flex-wrap: wrap; padding-top: 7px; border-top: 1px dashed #edf0f4; color: #9096a2; font-size: 10px; }
.mono, code { font-family: Consolas, 'Cascadia Code', monospace; overflow-wrap: anywhere; }
.flow-strip { justify-content: space-between; gap: 8px; margin-bottom: 10px; padding: 10px 13px; border: 1px solid #e3eaf2; border-radius: 9px; background: #fff; }
.flow-strip > div { display: flex; align-items: center; gap: 7px; flex: 1; color: #7a8491; font-size: 12px; }
.flow-strip i { width: 23px; height: 23px; display: grid; place-items: center; border-radius: 50%; background: #edf1f6; font-size: 11px; font-style: normal; }
.flow-strip .done { color: #383c41; }.flow-strip .done i { color: #fff; background: #34a46f; }.flow-strip .current i { outline: 2px solid #b8d8ff; }
.workspace { display: flex; align-items: flex-start; gap: 11px; }
.main-panel, .trace-panel { min-width: 0; }
.main-panel { flex: 1; padding: 0 14px 14px; }
.main-panel :deep(.el-tabs__header) { margin-bottom: 4px; }
.main-panel :deep(.el-tabs__item) { font-weight: 600; }
.trace-panel { width: 320px; flex: 0 0 320px; padding: 14px; }
.section { padding: 10px 0 2px; }
.section-head { justify-content: space-between; gap: 11px; margin-bottom: 10px; }
.section-head h3 { margin: 0 0 4px; font-size: 16px; }
.section-head h4 { margin: 0; font-size: 14px; }
.section-head p { margin: 0; color: #7a8491; font-size: 11px; line-height: 1.45; }
.two-col { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 9px; margin-bottom: 9px; }
.info-card { min-width: 0; padding: 12px 13px; border: 1px solid #e8edf3; border-radius: 8px; background: #fff; }
.info-card h4 { margin: 0 0 9px; font-size: 13px; }
.info-card > p { color: #383c41; font-size: 12px; line-height: 1.6; }
.info-card dl { margin: 0; }
.info-card dl > div { display: grid; grid-template-columns: 78px minmax(0,1fr); gap: 8px; padding: 6px 0; border-top: 1px solid #f0f2f5; }
.info-card dl > div:first-child { border-top: 0; }
.info-card dt { color: #9096a2; font-size: 11px; }.info-card dd { min-width: 0; margin: 0; color: #383c41; font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.photo-ref { display: flex; align-items: center; gap: 8px; padding: 7px; margin-top: 6px; background: #f7faff; border-radius: 6px; }
.photo-ref > span, .report-file { width: 30px; height: 30px; flex: 0 0 30px; display: grid; place-items: center; color: #007bff; background: #e6f2ff; border-radius: 6px; font-size: 11px; font-weight: 700; }
.photo-ref strong, .photo-ref small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.photo-ref strong { font-size: 11px; }.photo-ref small { max-width: 520px; margin-top: 3px; color: #9096a2; font-size: 10px; }
.notice { padding: 8px 10px; color: #84612b !important; background: #fff8e9; border-radius: 6px; }
.action-row { gap: 8px; flex-wrap: wrap; margin-top: 10px; }.action-row small { color: #9096a2; font-size: 10px; }
.stage-switch { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; color: #617185; font-size: 11px; }.stage-switch small { color: #9096a2; }
.p6-card { background: #fbfdff; }.grade-grid { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 6px; }
.grade-grid > div { padding: 8px 5px; text-align: center; background: #f2f7fd; border-radius: 6px; }.grade-grid span, .grade-grid strong, .grade-grid small { display: block; }.grade-grid span { color: #617185; font-size: 9px; }.grade-grid strong { margin: 4px 0 2px; color: #007bff; font-size: 16px; }.grade-grid small { color: #9096a2; font-size: 10px; }
.rain-line { margin: 9px 0 0 !important; color: #617185 !important; font-size: 10px !important; }.asset-values { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 7px; color: #617185; font-size: 10px; }
details { margin-top: 9px; }summary { color: #007bff; font-size: 11px; cursor: pointer; }pre { max-height: 200px; overflow: auto; margin: 7px 0 0; padding: 9px; color: #455363; background: #f6f8fb; border-radius: 6px; font: 10px/1.5 Consolas,monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.task-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 14px 0 9px; }.task-head h4 { margin: 0; font-size: 14px; }.task-head p { margin: 4px 0 0; color: #7a8491; font-size: 10px; }
.task-list, .report-list { display: grid; gap: 8px; }.task-card, .report-row { padding: 10px 11px; border: 1px solid #e8edf3; border-radius: 8px; background: #fff; }.task-top { justify-content: space-between; gap: 8px; }.task-top strong { display: flex; align-items: center; gap: 7px; font-size: 12px; }.task-top i { padding: 3px 5px; color: #007bff; background: #eff6ff; border-radius: 4px; font-size: 9px; font-style: normal; }
.task-card > p { margin: 8px 0; color: #383c41; font-size: 11px; line-height: 1.55; }.task-meta { gap: 7px 12px; flex-wrap: wrap; color: #7a8491; font-size: 10px; }.task-record { display: grid; gap: 3px; padding: 7px 0; border-top: 1px solid #f0f2f5; font-size: 10px; }.task-record small { color: #9096a2; }.task-record span { color: #383c41; }.task-record.reviewed { background: #f6fbf8; }.task-empty { padding: 8px 0; border-top: 1px solid #f0f2f5; color: #9096a2; font-size: 10px; }.task-foot { justify-content: space-between; gap: 8px; padding-top: 7px; border-top: 1px dashed #edf0f4; color: #a6acb8; font-size: 9px; }.task-foot small { color: #34a46f; }
.report-actions { margin-bottom: 10px; }.report-row { display: flex; align-items: center; gap: 8px; }.report-copy { min-width: 0; flex: 1; }.report-copy strong, .report-copy span, .report-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.report-copy strong { font-size: 12px; }.report-copy span { margin-top: 3px; color: #617185; font-size: 10px; }.report-copy small { margin-top: 3px; color: #9096a2; font-size: 9px; }.qa-card { margin-top: 10px; }.qa-controls { display: flex; gap: 8px; }.qa-controls .el-input { flex: 1; }.json-block { max-height: 180px; }
.inline-empty { padding: 16px; color: #9096a2; text-align: center; background: #f8fafc; border-radius: 6px; font-size: 11px; }
.counts { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 5px; padding: 8px; background: #f5f8fc; border-radius: 7px; }.counts > div { text-align: center; }.counts strong, .counts span { display: block; }.counts strong { color: #007bff; font-size: 16px; }.counts span { margin-top: 2px; color: #7a8491; font-size: 9px; }
.trace-panel .section-head h3 { margin: 0 0 3px; font-size: 15px; }.trace-panel .section-head p { margin: 0; color: #9096a2; font-size: 10px; }.trace-list { max-height: 620px; overflow: auto; margin-top: 7px; }.trace-row { align-items: flex-start; gap: 8px; padding: 9px 0; border-bottom: 1px solid #f0f2f5; }.trace-row > i { width: 8px; height: 8px; flex: 0 0 8px; margin-top: 5px; border-radius: 50%; background: #a6acb8; }.trace-row > i.success { background: #34a46f; }.trace-row > i.warning { background: #ff922c; }.trace-row > i.danger { background: #dd4739; }.trace-row > div { min-width: 0; flex: 1; }.trace-row strong { font-size: 11px; }.trace-row strong small { color: #617185; font-weight: 500; }.trace-row p { margin: 4px 0; color: #617185; font-size: 10px; }.trace-row div > small { display: block; color: #a6acb8; font-size: 9px; overflow-wrap: anywhere; }.error-text { color: #b83e35; font-size: 10px; }
.report-preview { max-height: 64vh; overflow: auto; color: #383c41; font-size: 13px; line-height: 1.7; }.report-preview :deep(h1), .report-preview :deep(h2), .report-preview :deep(h3) { margin: 16px 0 8px; }.report-preview :deep(p) { margin: 7px 0; }.report-preview :deep(table) { width: 100%; border-collapse: collapse; }.report-preview :deep(th), .report-preview :deep(td) { padding: 6px; border: 1px solid #e3eaf2; text-align: left; }
@media (max-width: 1280px) { .workspace { align-items: stretch; flex-direction: column; }.trace-panel { width: auto; flex-basis: auto; }.trace-list { max-height: 300px; } }
@media (max-width: 760px) { .page-head, .scenario-list, .scenario-card { display: flex; align-items: stretch; flex-direction: column; }.scenario-list button { min-width: 0; }.scenario-actions { justify-content: flex-start; }.event-heading { align-items: flex-start; flex-direction: column; }.event-facts { align-items: flex-start; flex-wrap: wrap; }.event-facts > div { flex-basis: 50%; }.flow-strip { align-items: flex-start; flex-direction: column; }.flow-strip > div { width: 100%; }.two-col { grid-template-columns: 1fr; }.grade-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }.report-row { align-items: flex-start; flex-wrap: wrap; }.report-copy { flex-basis: calc(100% - 44px); } }
</style>
