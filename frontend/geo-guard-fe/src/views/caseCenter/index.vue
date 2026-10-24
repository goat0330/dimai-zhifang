<template>
  <main class="case-center">
    <header class="head">
      <div><small>地脉智防 · 多智能体协同</small><h1>协同处置中心</h1><p>现场发现—监测研判—处置审核—任务反馈—复盘报告</p></div>
      <el-button plain type="primary" @click="$router.push('/ai-studio')">进入专业知识工作台</el-button>
    </header>
    <div class="notice"><strong>案例数据说明</strong>：本模块提供可复现的业务流程。部分现场、监测、人员和反馈记录为合成资料，不代表真实监测数据、正式预警或行政处置；P6风险值来自随软件交付的历史时片。</div>
    <section class="toolbar">
      <span>业务案例</span>
      <strong>秭归 · 监测告警与恢复跟踪</strong>
      <el-button type="primary" :loading="busy === 'start'" @click="start">建立事件流程</el-button>
      <el-button :disabled="!runId" :loading="busy === 'refresh'" @click="refresh">刷新持久化记录</el-button>
    </section>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <template v-if="runId">
      <section class="overview">
        <div class="section-overline">当前事件 <el-tag :type="finished ? 'success' : 'warning'">{{ finished ? '已完成' : '处理中' }}</el-tag></div>
        <h2>{{ event.event_name || event.title || '宜昌地质灾害业务事件' }}</h2>
        <p>{{ event.summary || event.description || '详情以已保存的业务记录为准。' }}</p>
        <div class="facts"><div><span>事件编号</span><b>{{ event.event_id || runId }}</b></div><div><span>任务</span><b>{{ tasks.length }}</b></div><div><span>反馈</span><b>{{ feedbacks.length }}</b></div><div><span>报告</span><b>{{ reports.length }}</b></div></div>
      </section>
      <h2 class="section-title">操作流程</h2>
      <div class="steps">
        <article class="step"><small>01 / 风险感知</small><h3>监测与动态风险</h3><p>记录监测阶段并关联P6风险时片，保留数据来源和监测状态。</p><el-button :disabled="Boolean(busy) || executed('A3', stage)" :loading="busy === 'a3'" @click="act('a3', () => executeGoldA3(runId, stage))">{{ executed('A3', stage) ? '当前阶段已保存' : '执行当前阶段研判' }}</el-button></article>
        <article class="step"><small>02 / 辅助决策</small><h3>处置建议与审核</h3><p>从专业依据和事件记录生成候选措施，需明确审核后才能形成任务。</p><div class="buttons"><el-button :disabled="Boolean(busy) || executed('A4')" @click="act('a4', () => executeGoldA4(runId))">生成处置建议</el-button><el-button type="primary" plain :disabled="Boolean(busy) || !executed('A4') || planApproved" @click="act('plan', () => reviewGoldPlan(runId))">确认案例方案</el-button></div></article>
        <article class="step"><small>03 / 任务反馈</small><h3>执行反馈与逐项复核</h3><p>反馈和复核保存在同一事件链。秭归案例须先记录恢复阶段，方可逐项复核。</p><div class="buttons"><el-button :disabled="Boolean(busy) || !planApproved || stageFeedbackSaved" @click="act('feedback', () => replayGoldFeedback(runId, stage))">{{ stageFeedbackSaved ? '当前阶段反馈已保存' : '写入当前阶段案例反馈' }}</el-button><el-button v-for="task in tasks.filter(t => !reviewed(t))" :key="task.task_id" :disabled="Boolean(busy) || !canReviewTasks" @click="act('review', () => reviewGoldTask(runId, task.fixture_task_key))">复核任务{{ String(task.task_id || '').slice(-5) }}</el-button></div></article>
        <article v-if="scenario === 'GOLD-02'" class="step"><small>04 / 恢复观察</small><h3>追加恢复阶段</h3><p>先保存异常阶段反馈，再延续同一事件和任务链记录恢复阶段。</p><el-button :disabled="Boolean(busy) || !initialFeedbackSaved || hasRecovery" @click="recovery">{{ hasRecovery ? '恢复阶段已建立' : '建立恢复阶段' }}</el-button><el-radio-group v-if="hasRecovery" v-model="stage" class="stage"><el-radio-button value="GOLD-02">异常阶段</el-radio-button><el-radio-button value="GOLD-03">恢复阶段</el-radio-button></el-radio-group></article>
        <article class="step"><small>{{ scenario === 'GOLD-02' ? '05' : '04' }} / 成果归档</small><h3>复盘报告</h3><p>依据持久化事实生成DOCX，审核后完成本次案例事件。</p><div class="buttons"><el-button :disabled="Boolean(busy) || !allReviewed" @click="act('report', () => createGoldRetrospective(runId))">生成复盘报告</el-button><el-button type="primary" plain :disabled="Boolean(busy) || !finalReport || finished" @click="act('final', () => reviewGoldFinalReport(runId))">审核报告</el-button><el-button v-if="finalReport" link type="primary" :disabled="Boolean(busy)" @click="download">下载DOCX</el-button></div></article>
      </div>
      <section class="records"><h2>持久化记录</h2><p>下列数量来自本次事件的业务数据库读取结果。</p><div class="counts"><div v-for="r in counts" :key="r.key"><span>{{ r.name }}</span><b>{{ r.num }}</b></div></div></section>
    </template>
    <el-empty v-else description="选择业务案例，建立事件后即可开始协同处置" />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { startGoldRun, readGoldRun, executeGoldA3, executeGoldA4, reviewGoldPlan, replayGoldFeedback, reviewGoldTask, executeGoldRecovery, createGoldRetrospective, reviewGoldFinalReport, downloadGoldReport } from '@/api/yichangGold.js'

defineOptions({ name: 'BusinessCaseCenter' })
const scenario = ref('GOLD-02')
const stage = ref('GOLD-02')
const snap = ref(null)
const busy = ref('')
const error = ref('')
const runId = computed(() => snap.value?.run?.run_id || '')
const event = computed(() => snap.value?.event?.payload || snap.value?.event || {})
const group = computed(() => snap.value?.records || {})
const rows = key => (group.value[key] || []).map(row => row?.payload || row)
const tasks = computed(() => rows('task'))
const feedbacks = computed(() => rows('feedback'))
const reports = computed(() => rows('report'))
const approvals = computed(() => rows('approval'))
const executions = computed(() => rows('dify_execution'))
const finalReport = computed(() => reports.value.filter(x => x.report_type === 'retrospective' && x.status !== 'superseded').at(-1))
const finished = computed(() => event.value.status === 'completed' && finalReport.value?.review_status === 'approved')
const planApproved = computed(() => Boolean(snap.value?.run?.plan_review_id || approvals.value.some(x => x.approval_type === 'plan' || x.plan_fixture_key)))
const hasRecovery = computed(() => rows('monitoring_assessment').some(x => x.stage_id === 'GOLD-03'))
const initialFeedbackSaved = computed(() => feedbacks.value.some(x => String(x.data_source || '').includes(':GOLD-02:')))
const recoveryFeedbackSaved = computed(() => feedbacks.value.some(x => String(x.data_source || '').includes(':GOLD-03:')))
const stageFeedbackSaved = computed(() => scenario.value === 'GOLD-01' ? feedbacks.value.length > 0 : stage.value === 'GOLD-02' ? initialFeedbackSaved.value : recoveryFeedbackSaved.value)
const canReviewTasks = computed(() => scenario.value === 'GOLD-01' ? feedbacks.value.length > 0 : (hasRecovery.value && recoveryFeedbackSaved.value))
const executed = (agent, phase) => executions.value.some(x => x.agent_id === agent && (!phase || x.stage_id === phase))
const reviewed = task => rows('task_review').some(x => x.task_id === task.task_id || x.task_fixture_key === task.fixture_task_key)
const allReviewed = computed(() => tasks.value.length > 0 && tasks.value.every(reviewed))
const counts = computed(() => [{ key: 'discovery', name: '发现', num: rows('discovery').length }, { key: 'monitoring_assessment', name: '监测', num: rows('monitoring_assessment').length }, { key: 'dify_execution', name: '智能体执行', num: executions.value.length }, { key: 'task', name: '任务', num: tasks.value.length }, { key: 'feedback', name: '反馈', num: feedbacks.value.length }, { key: 'report', name: '报告', num: reports.value.length }])
const key = () => 'dimai:case:' + scenario.value
async function load(id) { snap.value = await readGoldRun(id); localStorage.setItem(key(), id) }
async function restore() { snap.value = null; error.value = ''; stage.value = scenario.value; const id = localStorage.getItem(key()); if (id) try { await load(id) } catch { localStorage.removeItem(key()) } }
async function start() { busy.value = 'start'; error.value = ''; try { const x = await startGoldRun(scenario.value); const id = x.run?.run_id || x.run_id; if (!id) throw new Error('业务服务未返回事件编号'); await load(id); ElMessage.success('事件已建立') } catch (e) { error.value = e.message || '建立事件失败' } finally { busy.value = '' } }
async function refresh() { await act('refresh', async () => {}) }
async function act(keyName, operation) { if (!runId.value || busy.value) return; busy.value = keyName; error.value = ''; try { await operation(); await load(runId.value); ElMessage.success('业务记录已更新') } catch (e) { error.value = e.message || '执行失败，请查看服务日志' } finally { busy.value = '' } }
async function recovery() { await act('recovery', () => executeGoldRecovery(runId.value)); if (hasRecovery.value) stage.value = 'GOLD-03' }
async function download() { if (!finalReport.value?.report_id) return; busy.value = 'download'; try { const blob = await downloadGoldReport(runId.value, finalReport.value.report_id); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = finalReport.value.docx_file_name || '地脉智防_复盘报告.docx'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) } catch (e) { error.value = e.message || '报告下载失败' } finally { busy.value = '' } }
onMounted(restore)
</script>

<style scoped>
.case-center{padding:30px 36px 48px;width:100%;box-sizing:border-box;overflow-y:auto;color:#233947}.head{display:flex;justify-content:space-between;gap:20px}.head h1{font-size:27px;margin:8px 0}.head small,.step small{color:#297c81;font-weight:700}.head p,.overview p,.records p{color:#697e89}.notice{margin:20px 0;padding:16px;background:#f2f7f5;border:1px solid #d8e7e1;border-left:3px solid #33887a;font-size:13px;line-height:1.8}.toolbar,.overview,.records{background:#fff;border:1px solid #e0e8ed;border-radius:10px;padding:20px;margin-bottom:18px}.toolbar{display:flex;align-items:center;gap:12px}.toolbar :deep(.el-select){width:270px}.section-overline{display:flex;align-items:center;gap:10px;color:#52838d;font-size:12px}.overview h2{margin:10px 0}.facts{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:12px;margin-top:18px}.facts div,.counts div{background:#f4f7f8;padding:12px;overflow-wrap:anywhere}.facts span,.counts span{display:block;color:#6f8088;font-size:12px}.facts b,.counts b{display:block;margin-top:8px}.section-title{font-size:20px;margin:24px 0 14px}.steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.step{border:1px solid #e1e8ed;border-radius:10px;padding:20px;display:flex;flex-direction:column;align-items:start;min-height:220px}.step h3{font-size:17px;margin:10px 0}.step p{font-size:13px;line-height:1.7;color:#617581;flex:1}.buttons{display:flex;gap:7px;flex-wrap:wrap}.buttons :deep(.el-button){margin-left:0}.stage{margin-top:12px}.records{margin-top:24px}.counts{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}.counts b{font-size:22px}@media(max-width:1100px){.steps{grid-template-columns:repeat(2,minmax(0,1fr))}.counts{grid-template-columns:repeat(3,1fr)}}@media(max-width:720px){.case-center{padding:18px}.head,.toolbar{flex-direction:column;align-items:stretch}.steps{grid-template-columns:1fr}.facts{grid-template-columns:repeat(2,1fr)}.counts{grid-template-columns:repeat(2,1fr)}}
</style>
