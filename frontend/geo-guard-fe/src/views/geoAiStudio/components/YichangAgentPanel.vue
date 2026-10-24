<template>
  <section class="yichang-panel" aria-labelledby="yichang-title">
    <header class="panel-heading">
      <div>
        <span class="eyebrow">宜昌地脉智防</span>
        <h2 id="yichang-title">宜昌智能体协同工作台</h2>
        <p>围绕秭归市事件开展监测研判、处置建议、任务反馈与复盘归档。</p>
      </div>
      <span class="simulated-pill">秭归市事件处置</span>
    </header>

    <div class="agent-grid" aria-label="宜昌智能体状态">
      <article v-for="agent in agentCards" :key="agent.id" class="agent-card">
        <span class="agent-id">{{ agent.id }}</span>
        <div>
          <strong>{{ agent.name }}</strong>
          <small>{{ agentStatusLabel(agent.status) }}</small>
          <small>智能体服务：{{ agentDifyLabel(agent.id) }}</small>
        </div>
      </article>
    </div>
    <p class="simulation-note">智能体服务状态表示接口配置情况；具体处理结果以本次实际调用返回内容为准。</p>

    <div class="run-row">
      <label for="gold-scenario">业务场景</label>
      <select id="gold-scenario" v-model="scenarioId" :disabled="running" @change="loadGoldRecords()">
        <option value="GOLD-02">秭归市事件 · 告警处置与恢复观察</option>
      </select>
      <button type="button" :disabled="running" @click="runScenario">
        {{ running ? '研判中…' : '执行事件研判' }}
      </button>
      <button type="button" class="secondary-button" :disabled="goldReadbackLoading || running" @click="loadGoldRecords()">
        {{ goldReadbackLoading ? '读取中…' : '刷新事件记录' }}
      </button>
      <span v-if="agentsError" class="inline-error">智能体状态暂不可用</span>
    </div>
    <p v-if="goldReadbackStatus" class="persisted-note">{{ goldReadbackStatus }}</p>
    <p v-if="goldReadbackError" class="error-message" role="alert">{{ goldReadbackError }}</p>

    <p class="simulation-note">
      研判与处置记录保存在本地事件业务库；当前流程不触发正式任务派发或预警发布。
    </p>

    <p v-if="runError" class="error-message" role="alert">{{ runError }}</p>
    <section v-if="result" class="run-result" aria-live="polite">
      <div class="result-heading">
        <div>
            <span class="result-status">{{ scenarioTitle(result.scenario_id) }} · 研判完成</span>
            <p>事件资料已关联保存</p>
        </div>
          <span class="simulated-pill">{{ result.is_simulated ? '随附事件资料' : '事件业务记录' }}</span>
      </div>
      <div class="result-grid">
        <div><small>知识检索</small><strong>{{ result.rag?.status }} · {{ result.rag?.evidence_count || 0 }} 条证据</strong></div>
        <div v-if="result.a2"><small>A2 现场识别</small><strong>{{ result.a2.image_analysis_status }}</strong></div>
        <div v-if="result.a3"><small>A3 监测回放</small><strong>{{ result.a3.status }}</strong></div>
        <div><small>A4 研判</small><strong>{{ result.a4?.decision_status }}</strong></div>
        <div><small>处置任务记录</small><strong>{{ result.java_task?.status }} · 保存在本地事件记录</strong></div>
        <div><small>A5 报告</small><strong>{{ result.a5?.status }}</strong></div>
      </div>
      <section v-if="result.a2?.field_investigation_record" class="field-investigation-card" aria-label="宜昌现场调查记录">
        <div class="result-heading">
          <div>
            <span class="result-status">A2 现场调查记录</span>
            <p>{{ result.a2.admin_area || '宜昌市' }} · 现场调查记录</p>
          </div>
          <span class="simulated-pill">{{ result.a2.is_simulated ? '随附现场资料' : '现场调查记录' }}</span>
        </div>
        <div class="field-record-grid">
          <section v-for="section in fieldInvestigationSections(result.a2.field_investigation_record)" :key="section.title" class="field-record-section">
            <h4>{{ section.title }}</h4>
            <dl>
              <div v-for="item in section.values" :key="item.label">
                <dt>{{ item.label }}</dt>
                <dd>{{ formatFieldRecordValue(item.value) }}</dd>
              </div>
            </dl>
          </section>
        </div>
      </section>
      <section v-if="result.a4?.a4_review || result.a4?.recommendation" class="flow-result">
        <div class="result-heading">
          <div>
            <span class="result-status">A4 研判意见 · 待人工确认</span>
            <p>执行引擎 {{ result.a4.recommendation_engine || result.a4.execution_engine || '—' }}</p>
          </div>
          <span class="simulated-pill">{{ result.a4.is_simulated ? '待现场核实' : '候选研判' }}</span>
        </div>
        <p class="recommendation">{{ result.a4.a4_review?.current_judgment || result.a4.recommendation || '未返回研判正文' }}</p>
        <ul v-if="result.a4.a4_review?.action_items?.length" class="finding-list">
          <li v-for="(item, index) in result.a4.a4_review.action_items" :key="`${item.action}-${index}`">
            {{ item.action }}
          </li>
        </ul>
        <ul v-if="result.a4.review_basis?.evidence?.length" class="finding-list">
          <li v-for="item in result.a4.review_basis.evidence" :key="item.evidence_id || item.chunk_id">
            依据 {{ item.evidence_id || item.chunk_id || '未编号证据' }} · {{ item.file_name || item.document_id || '宜昌知识库' }}
            <span v-if="item.page"> · 第 {{ item.page }} 页</span>
          </li>
        </ul>
      </section>
      <details v-if="result.a4?.a4_execution?.workflows" class="p6-result">
        <summary>智能体协同记录</summary>
        <p v-for="(execution, role) in result.a4.a4_execution.workflows" :key="role">
          <strong>{{ execution.app_name || role }}</strong>
          · {{ execution.execution_engine }} / {{ execution.status }} / {{ execution.output_status || '无结构化状态' }}<br />
        </p>
      </details>
      <details v-if="result.a4?.a4_execution?.workflows?.plan" class="p6-result">
        <summary>A4 处置方案正文 · {{ result.a4.a4_execution.workflows.plan.output_status || '状态待核验' }}</summary>
        <pre v-if="result.a4.a4_execution.workflows.plan.plan_text" class="draft-preview">{{ result.a4.a4_execution.workflows.plan.plan_text }}</pre>
        <p v-else>这条已保存记录没有处置方案正文；新执行会按当前适配器保留 Dify 文本输出。</p>
      </details>
      <details v-if="result.a4?.p6_snapshot || result.a4?.p6_dynamic_snapshot" class="p6-result">
        <summary>P6 候选四性与动态时片 · 不作为官方预警</summary>
        <p>坡单元映射：{{ result.a4.p6_mapping?.p6_slope_unit_id || result.event?.p6_mapping?.p6_slope_unit_id || '未提供' }} · {{ result.a4.p6_mapping?.mapping_status || '候选/待核验' }}</p>
        <pre>{{ JSON.stringify({ static: result.a4.p6_snapshot, dynamic: result.a4.p6_dynamic_snapshot }, null, 2) }}</pre>
      </details>
      <details v-if="result.a3?.monitoring?.series?.length" class="monitor-series">
        <summary>A3 监测时序（{{ result.a3.monitoring.series.length }} 条）</summary>
        <p>时序资料的来源与核验状态以本事件记录为准；研判结果仅供业务参考，预警发布按正式流程办理。</p>
        <div class="series-scroll">
          <table>
            <thead><tr><th>时间</th><th>短时雨量 mm</th><th>连续雨量 mm</th><th>位移 mm</th><th>速率 mm/日</th><th>库水位 m</th><th>库水位趋势</th><th>恢复</th></tr></thead>
            <tbody>
              <tr v-for="(row, index) in result.a3.monitoring.series" :key="row.observed_at || index">
                <td>{{ row.observed_at || '—' }}</td><td>{{ row.short_term_rainfall_mm ?? '—' }}</td>
                <td>{{ row.continuous_rainfall_mm ?? '—' }}</td><td>{{ row.displacement_mm ?? '—' }}</td>
                <td>{{ row.displacement_rate_mm_per_day ?? '—' }}</td><td>{{ row.reservoir_level_m ?? '—' }}</td>
                <td>{{ row.reservoir_trend || '—' }}</td><td>{{ row.recovery ? '是' : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
      <section class="gold-actions" aria-label="秭归市事件处置记录">
        <h3>人工审核与处置记录</h3>
        <p class="simulation-note">任务、反馈和报告保存在本地事件业务库；当前未接入正式任务派发和预警发布系统。</p>
        <label>审核人标识<input v-model.trim="goldReviewerId" required placeholder="填写审核人姓名或标识" /></label>
        <div v-if="result.task_proposal" class="gold-action-review">
          <strong>待审核行动项</strong>
          <p v-if="result.task_proposal.action_source === 'dify_a4_review'" class="simulation-note">
            当前草稿默认采用 Dify A4 主分析建议；这只是待审核建议，尚未派发。未关联证据时不会借用其他行动项的证据。
          </p>
          <ul v-if="result.task_proposal.a4_action_suggestions?.length > 1" class="finding-list">
            <li v-for="(suggestion, index) in result.task_proposal.a4_action_suggestions" :key="`${suggestion.action}-${index}`">
              A4 建议 {{ index + 1 }}：{{ suggestion.action }}（依据 {{ suggestion.basis_evidence_ids?.length || 0 }} 项）
            </li>
          </ul>
          <p class="simulation-note">当前点位与 P6 坡单元的空间关系仍待现场核实；任务位置、责任部门、负责人及完成时限请由审核人确认。</p>
          <div class="field-form gold-action-form">
            <label>行动项<input v-model.trim="goldActionDraft.action" :disabled="!!goldTaskId" /></label>
            <label>任务位置<input v-model.trim="goldActionDraft.location" :disabled="!!goldTaskId" /></label>
            <label>责任部门<input v-model.trim="goldActionDraft.responsible_department" :disabled="!!goldTaskId" placeholder="由审核人指定" /></label>
            <label>责任人<input v-model.trim="goldActionDraft.person" :disabled="!!goldTaskId" placeholder="由审核人指定" /></label>
            <label class="wide-field">完成时限<input v-model.trim="goldActionDraft.due_at" :disabled="!!goldTaskId" placeholder="2026-10-16T18:00:00+08:00" /></label>
            <label class="wide-field">完成标准<textarea v-model.trim="goldActionDraft.completion_criteria" :disabled="!!goldTaskId" rows="2"></textarea></label>
          </div>
          <ul v-if="result.task_proposal.action?.basis_evidence_ids?.length" class="finding-list">
            <li v-for="evidenceId in result.task_proposal.action.basis_evidence_ids" :key="evidenceId">依据 {{ evidenceId }}</li>
          </ul>
          <p v-else-if="result.task_proposal.action_source === 'dify_a4_review'" class="simulation-note">
            当前 A4 行动项没有可引用证据 ID；请审核人核验事实或补充依据后再决定是否提交。
          </p>
        </div>
        <div class="approval-row">
          <button type="button" :disabled="goldTaskRunning || !!goldTaskId || !goldReviewerId || !result.event_id || !result.task_proposal || !goldTaskActionReady"
            @click="approveGoldTask">
            {{ goldTaskRunning ? '保存审核中…' : scenarioId === 'GOLD-03' ? '确认恢复核查' : '审核并保存任务记录' }}
          </button>
          <span v-if="goldTaskId" class="persisted-note">任务记录编号 {{ goldTaskId }} · {{ goldTaskState?.status || result.java_task?.status }}</span>
        </div>
        <p v-if="goldTaskError" class="error-message" role="alert">{{ goldTaskError }}</p>
        <label class="wide-field">现场处置反馈<textarea v-model.trim="goldFeedbackText" rows="2"
          placeholder="记录现场核查或恢复观察情况；提交后与当前事件及任务关联保存" /></label>
        <div class="approval-row">
          <button type="button" :disabled="goldFeedbackRunning || !goldTaskId || !goldReviewerId || !goldFeedbackText"
            @click="submitGoldFeedback">
            {{ goldFeedbackRunning ? '保存反馈中…' : '审核并保存处置反馈' }}
          </button>
          <span v-if="goldFeedbackStatus" class="persisted-note">{{ goldFeedbackStatus }}</span>
        </div>
        <p v-if="goldFeedbackError" class="error-message" role="alert">{{ goldFeedbackError }}</p>
        <p v-if="!goldTaskId || !goldFeedbackStatus" class="simulation-note">
          先完成人工任务审核并保存现场反馈；A5 只读取持久化后的同事件事实。
        </p>
        <div class="approval-row">
          <button type="button" class="secondary-button" :disabled="goldReportRunning || !result.event_id || !goldTaskId || !goldFeedbackStatus"
            @click="buildGoldReportDraft">
            {{ goldReportRunning ? '生成中…' : '根据已保存记录生成复盘报告' }}
          </button>
        </div>
        <article v-if="goldReportDraft" class="flow-result">
          <div class="result-heading">
            <div><span class="result-status">A5 {{ goldReportDraft.status }}</span><p>报告 ID：{{ goldReportId || '待生成' }}</p></div>
            <span class="simulated-pill">待核验资料</span>
          </div>
          <p v-if="goldReportDraft.missing_fields?.length" class="muted-copy">尚缺：{{ goldReportDraft.missing_fields.join('、') }}</p>
          <label class="wide-field">人工补充/修改复盘结论<textarea v-model.trim="goldReportConclusion" rows="3"
            placeholder="审核人补充结论；不会改写已保存的事件、任务或反馈事实" /></label>
          <div class="approval-row">
            <label class="check-field"><input v-model="goldReportApproved" type="checkbox" />我已审核复盘报告</label>
            <label class="check-field"><input v-model="goldArchiveApproved" type="checkbox" />我确认归档至事件资料</label>
            <button type="button" :disabled="goldArchiveRunning || !goldReviewerId || !goldReportApproved || !goldArchiveApproved || !goldReportId"
              @click="archiveGoldReport">
              {{ goldArchiveRunning ? '保存中…' : '审核并归档报告' }}
            </button>
            <button type="button" class="secondary-button" :disabled="!goldArchiveResult?.document_id || goldVerifyRunning"
              @click="verifyGoldReport">
              {{ goldVerifyRunning ? '检索中…' : '检索并核验报告' }}
            </button>
          </div>
          <p v-if="goldArchiveStatus" class="persisted-note">{{ goldArchiveStatus }}</p>
          <p v-if="goldVerifyStatus" class="persisted-note">{{ goldVerifyStatus }}</p>
          <p v-if="goldArchiveError" class="error-message" role="alert">{{ goldArchiveError }}</p>
          <p class="muted-copy">报告内容按事件记录整理；缺少现场核查或审核信息的部分会单独标示。</p>
        </article>
      </section>
    </section>

    <section class="field-flow" aria-label="宜昌现场事件业务链">
      <div class="flow-heading">
        <div>
          <h3>A2 → A4 → Java → A5 现场事件主链</h3>
          <p>先整理现场证据，再生成待审核建议。Java 任务、反馈和证据库归档都由人工按钮触发。</p>
        </div>
        <span class="flow-state">宜昌范围</span>
      </div>

      <form class="field-form" @submit.prevent="runFieldAnalysis">
        <label>市级范围<input value="宜昌市" disabled /></label>
        <label>县市区<input v-model.trim="fieldForm.county" placeholder="如：五峰土家族自治县" /></label>
        <label>斜坡单元 ID<input v-model.trim="fieldForm.slopeUnitId" placeholder="填 Java 业务库中的真实 ID" /></label>
        <label>P6 斜坡单元 ID<input v-model.trim="fieldForm.p6SlopeUnitId" placeholder="YCSV2_…；按宜昌坡面风险评价单元核对后填写" @input="fieldForm.p6MappingConfirmed = false" /></label>
        <label class="check-field"><input v-model="fieldForm.p6MappingConfirmed" type="checkbox" :disabled="!fieldForm.p6SlopeUnitId" />我已核对该 P6 单元与本次上报位置一致</label>
        <label>隐患点 ID<input v-model.trim="fieldForm.hazardPointId" placeholder="有可靠关联时填写" /></label>
        <label>巡查时间<input v-model="fieldForm.visitTime" type="datetime-local" required /></label>
        <label>纬度<input v-model.trim="fieldForm.latitude" type="number" step="any" placeholder="GPS 纬度" /></label>
        <label>经度<input v-model.trim="fieldForm.longitude" type="number" step="any" placeholder="GPS 经度" /></label>
        <label class="wide-field">现场描述<textarea v-model.trim="fieldForm.narrative" rows="3" placeholder="记录巡查人员实际观察到的迹象" /></label>
        <label class="wide-field">现场照片<input type="file" accept="image/*" multiple @change="onFieldPhotosChange" /></label>
        <label class="wide-field">已有照片 OSS ID<textarea v-model.trim="fieldForm.photoRefs" rows="2" placeholder="每行一个已有的照片 OSS ID" /></label>
        <label class="check-field"><input v-model="fieldForm.isSimulated" type="checkbox" />该记录来自随软件交付的事件资料</label>
        <button type="submit" :disabled="fieldRunning || (!fieldForm.narrative && !fieldPhotos.length && !fieldForm.photoRefs)">
          {{ fieldRunning ? 'A2 整理中…' : '提交现场输入并运行 A2' }}
        </button>
      </form>
      <p class="simulation-note">P6 H/R 只使用已核对的 P6 单元 ID 查询；结果是 ECMWF IFS 模型降雨筛查候选，不是雨量站实测或官方预警。无法确认空间对应时可留空。</p>
      <p class="simulation-note">{{ a2DifyConfigured ? '现场图片将通过已配置的智能体服务处理；图片引用随事件记录保存。' : '当前未配置现场图片识别服务，照片引用可保存至事件记录，识别结果将在服务接入后提供。' }}</p>
      <p v-if="fieldError" class="error-message" role="alert">{{ fieldError }}</p>

      <article v-if="fieldResult" class="flow-result">
        <div class="result-heading">
          <div>
            <span class="result-status">A2 {{ fieldResult.event_status }}</span>
            <p>事件资料已关联 · {{ fieldResult.admin_area }}</p>
          </div>
          <span class="simulated-pill">{{ fieldResult.is_simulated ? '随附事件资料' : '现场记录' }}</span>
        </div>
        <p>文字分析：{{ fieldResult.text_analysis_status }} · 图片分析：{{ fieldResult.image_analysis_status }}</p>
        <ul v-if="fieldResult.findings?.length" class="finding-list">
          <li v-for="(finding, index) in fieldResult.findings" :key="`${finding.label}-${index}`">
            {{ finding.label }}<small v-if="finding.source_quote"> · 原文：{{ finding.source_quote }}</small>
          </li>
        </ul>
        <p v-else class="muted-copy">尚无经过证据核验的迹象标签；原始文字和照片引用仍保留。</p>
        <button type="button" :disabled="decisionRunning || fieldResult.event_status !== 'ready_for_a4_review'" @click="runFieldDecision">
          {{ decisionRunning ? 'A4 研判中…' : '送入共享 A4 研判' }}
        </button>
      </article>

      <p v-if="decisionError" class="error-message" role="alert">{{ decisionError }}</p>
      <article v-if="decisionResult" class="flow-result">
        <div class="result-heading">
          <div>
            <span class="result-status">A4 {{ decisionResult.decision_status }}</span>
            <p>知识检索：{{ decisionResult.rag_status }} · 引用 {{ decisionResult.review_basis?.evidence?.length || 0 }} 条</p>
          </div>
          <span class="simulated-pill">{{ decisionResult.is_simulated ? '待现场核实' : '待人工审核' }}</span>
        </div>
        <div class="model-grid">
          <div v-for="(model, key) in decisionResult.four_natures" :key="key">
            <small>{{ key }}</small><strong>{{ model.status }}</strong>
          </div>
        </div>
        <p class="recommendation">{{ decisionResult.recommendation }}</p>
        <ul v-if="decisionResult.review_basis?.evidence?.length" class="finding-list">
          <li v-for="item in decisionResult.review_basis.evidence" :key="item.evidence_id || item.chunk_id">
            {{ item.file_name || item.document_id }}<small v-if="item.page"> · 第 {{ item.page }} 页</small>
          </li>
        </ul>
        <div class="approval-row">
          <label class="check-field">
            <input v-model="taskApproval" type="checkbox" :disabled="!taskPayloadReady" />
            我已核验斜坡单元与责任网格关系，并批准创建核查任务
          </label>
          <button type="button" :disabled="creatingTask || !taskApproval || !taskPayloadReady" @click="createJavaTask">
            {{ creatingTask ? '创建中…' : '人工审核并创建核查任务' }}
          </button>
          <button type="button" class="secondary-button" :disabled="reportRunning" @click="createReportDraft">
            {{ reportRunning ? '生成中…' : '生成 A5 报告草案' }}
          </button>
        </div>
        <p v-if="taskError" class="error-message" role="alert">{{ taskError }}</p>
        <p v-if="taskId" class="persisted-note">任务编号 {{ taskId }} · {{ taskStatusLabel(taskDetail?.status) }}</p>
      </article>

      <div class="task-lookup">
        <label>读取已有任务编号<input v-model.trim="taskId" inputmode="numeric" placeholder="用于恢复已保存的任务和反馈" /></label>
        <button type="button" class="secondary-button" :disabled="taskRefreshing || !taskId" @click="refreshJavaTask">
          {{ taskRefreshing ? '读取中…' : '读取任务与反馈' }}
        </button>
      </div>
      <p v-if="taskError" class="error-message" role="alert">{{ taskError }}</p>

      <article v-if="taskId && taskDetail" class="flow-result">
        <div class="result-heading">
          <div><span class="result-status">处置任务 {{ taskId }}</span><p>任务派发或接单后可提交现场反馈。</p></div>
          <div class="approval-row">
            <button type="button" class="secondary-button" :disabled="taskRefreshing" @click="refreshJavaTask">刷新任务与反馈</button>
            <button type="button" class="secondary-button" :disabled="reportRunning" @click="createReportDraft">生成 A5 草案</button>
          </div>
        </div>
        <p v-if="Number(taskDetail?.status) === 1" class="muted-copy">任务尚未推送；请先由业务人员在现有任务流程中派发。</p>
        <form v-if="canSubmitFeedback" class="field-form feedback-form" @submit.prevent="submitJavaFeedback">
          <label>现场纬度<input v-model.trim="feedbackForm.latitude" type="number" step="any" required /></label>
          <label>现场经度<input v-model.trim="feedbackForm.longitude" type="number" step="any" required /></label>
          <label class="wide-field">核查反馈<textarea v-model.trim="feedbackForm.text" rows="2" required placeholder="填写实际核查结果" /></label>
          <label class="wide-field">反馈现场照片（至少 2 张）<input type="file" accept="image/*" multiple required @change="onFeedbackPhotosChange" /></label>
          <button type="submit" :disabled="feedbackRunning || feedbackPhotos.length < 2 || !currentUserId">
            {{ feedbackRunning ? '上传并提交中…' : '提交现场反馈并回读核验' }}
          </button>
        </form>
        <p v-if="feedbackError" class="error-message" role="alert">{{ feedbackError }}</p>
        <p v-if="feedbackStatus" class="persisted-note">{{ feedbackStatus }}</p>
        <ul v-if="taskFeedbacks.length" class="finding-list">
          <li v-for="feedback in taskFeedbacks" :key="feedback.id">
            {{ feedback.createDate || '已保存反馈' }} · {{ feedback.textRecord || feedback.remark }} · 状态 {{ feedback.submitStatus }}
          </li>
        </ul>
      </article>

      <article v-if="reportDraft" class="flow-result">
        <div class="result-heading">
          <div><span class="result-status">A5 {{ reportDraft.status }}</span><p>报告编号：{{ reportId || '待生成' }} · {{ reportDraft.review_status }}</p></div>
          <span class="simulated-pill">{{ reportDraft.is_simulated ? '待核验资料' : '待审核报告' }}</span>
        </div>
        <p>报告已关联当前事件记录。</p>
        <p v-if="reportDraft.missing_fields?.length" class="muted-copy">尚缺：{{ reportDraft.missing_fields.join('、') }}</p>
        <label class="wide-field">人工补充/修改复盘结论<textarea v-model.trim="reviewConclusion" rows="3" placeholder="审核人补充结论；不会改写源事件、任务或反馈事实" /></label>
        <div class="approval-row">
          <label class="check-field"><input v-model="reportApproved" type="checkbox" :disabled="reportDraft.is_simulated" />我已审核报告内容</label>
          <label class="check-field"><input v-model="archiveApproved" type="checkbox" :disabled="reportDraft.is_simulated" />我批准写入宜昌证据库</label>
          <button type="button" :disabled="archiving || !reportApproved || !archiveApproved || !reportId || reportDraft.is_simulated" @click="archiveReport">
            {{ archiving ? '归档中…' : '审核并归档到证据库' }}
          </button>
          <button type="button" class="secondary-button" :disabled="!archiveResult?.file_name || qaVerifying" @click="verifyArchivedReport">
            {{ qaVerifying ? 'A1 检索中…' : '用 A1 验证报告可检索' }}
          </button>
        </div>
        <p v-if="archiveStatus" class="persisted-note">证据库：{{ archiveStatus }}</p>
        <p v-if="archiveError" class="error-message" role="alert">{{ archiveError }}</p>
        <p class="muted-copy">报告依据当前事件记录生成；审核前请核实资料来源与待补充信息。</p>
      </article>
    </section>

    <section class="qa-box" aria-label="宜昌知识库问答">
      <div>
        <h3>A1 宜昌知识问答</h3>
        <p>回答将附三库证据；事件、任务、报告状态仍需 Java 业务上下文。</p>
      </div>
      <form @submit.prevent="askQuestion">
        <input v-model.trim="question" aria-label="宜昌知识库问题" placeholder="例如：宜昌地灾防治有哪些巡查依据？" />
        <button type="submit" :disabled="asking || !question">{{ asking ? '检索中…' : '检索问答' }}</button>
      </form>
      <p v-if="qaError" class="error-message" role="alert">{{ qaError }}</p>
      <div v-if="qaResult" class="qa-answer">
        <strong v-if="qaArchiveFound !== null" class="persisted-note">A1 回检：{{ qaArchiveFound ? '已检索到本次归档文件' : '当前结果未命中本次归档文件' }}</strong>
        <p>{{ qaResult.answer }}</p>
        <ul v-if="qaResult.evidence?.length">
          <li v-for="item in qaResult.evidence" :key="item.evidence_id || item.chunk_id">
            {{ item.knowledge_base_label || item.knowledge_base_id }} · {{ item.file_name || item.document_id }}
            <span v-if="item.page"> · 第 {{ item.page }} 页</span>
          </li>
        </ul>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { downloadFile } from '@/api/common.js'
import {
  archiveYichangReport,
  buildYichangReportDraft,
  confirmYichangGoldTask,
  getYichangAgents,
  getYichangGoldRecords,
  processYichangFieldReport,
  queryYichang,
  runYichangDecision,
  runYichangGold,
  submitYichangGoldFeedback,
} from '@/api/geoAiStudio.js'
import {
  addTaskDistList,
  getTaskDetail,
  getTaskFeedbacks,
  submitTaskFeedback,
  uploadTaskPhotos,
} from '@/api/task.js'
import { useUserStore } from '@/store/user.js'

defineOptions({ name: 'YichangAgentPanel' })

const scenarioId = ref('GOLD-02')
const running = ref(false)
const asking = ref(false)
const result = ref(null)
const runError = ref('')
const goldReadbackLoading = ref(false)
const goldReadbackStatus = ref('')
const goldReadbackError = ref('')
const question = ref('')
const qaResult = ref(null)
const qaError = ref('')
const agentStatus = ref({})
const agentsError = ref(false)
const agentsLoaded = ref(false)
const a2DifyConfigured = ref(false)
const difyApps = ref([])
const goldReviewerId = ref('')
const emptyGoldAction = () => ({
  action: '',
  location: '',
  responsible_department: '',
  person: '',
  due_at: '',
  completion_criteria: '',
})
const goldActionDraft = ref(emptyGoldAction())
const goldTaskActionReady = computed(() => {
  const action = goldActionDraft.value || {}
  const required = ['action', 'location', 'responsible_department', 'person', 'due_at', 'completion_criteria']
  const placeholders = new Set(['待分配', '待安排', '未指定'])
  return required.every((field) => {
    const value = String(action[field] || '').trim()
    return value && !placeholders.has(value)
  }) && /(?:Z|[+-]\d{2}:\d{2})$/.test(String(action.due_at || '').trim())
})
const goldTaskId = ref('')
const goldTaskState = ref(null)
const goldTaskRunning = ref(false)
const goldTaskError = ref('')
const goldFeedbackText = ref('')
const goldFeedbackRunning = ref(false)
const goldFeedbackStatus = ref('')
const goldFeedbackError = ref('')
const goldReportRunning = ref(false)
const goldReportDraft = ref(null)
const goldReportConclusion = ref('')
const goldReportApproved = ref(false)
const goldArchiveApproved = ref(false)
const goldArchiveRunning = ref(false)
const goldArchiveResult = ref(null)
const goldArchiveStatus = ref('')
const goldArchiveError = ref('')
const goldVerifyRunning = ref(false)
const goldVerifyStatus = ref('')
const userStore = useUserStore()
const currentUser = computed(() => userStore.userInfo?.user || userStore.userInfo || {})
const currentUserId = computed(() => currentUser.value.userId || '')
const fieldForm = ref({
  county: '',
  slopeUnitId: '',
  p6SlopeUnitId: '',
  p6MappingConfirmed: false,
  hazardPointId: '',
  visitTime: localDateTimeInput(),
  latitude: '',
  longitude: '',
  narrative: '',
  photoRefs: '',
  isSimulated: false,
})
const fieldPhotos = ref([])
const fieldRunning = ref(false)
const fieldResult = ref(null)
const fieldError = ref('')
const decisionRunning = ref(false)
const decisionResult = ref(null)
const decisionError = ref('')
const taskApproval = ref(false)
const creatingTask = ref(false)
const taskId = ref('')
const taskDetail = ref(null)
const taskFeedbacks = ref([])
const taskRefreshing = ref(false)
const taskError = ref('')
const feedbackForm = ref({ latitude: '', longitude: '', text: '' })
const feedbackPhotos = ref([])
const feedbackRunning = ref(false)
const feedbackError = ref('')
const feedbackStatus = ref('')
const reportRunning = ref(false)
const reportDraft = ref(null)
const reviewConclusion = ref('')
const reportApproved = ref(false)
const archiveApproved = ref(false)
const archiving = ref(false)
const archiveResult = ref(null)
const archiveStatus = ref('')
const archiveError = ref('')
const qaVerifying = ref(false)
const qaArchiveFound = ref(null)
const names = { A1: '地灾智能问答', A2: '现场险情发现', A3: '动态监测研判', A4: 'CUV 策略研判', A5: '复盘报告' }
const agentCards = computed(() => Object.entries(names).map(([id, name]) => ({
  id,
  name,
  status: agentStatus.value[id]?.status || 'checking',
})))
function fieldInvestigationSections(record = {}) {
  const basic = record.basic_field_info || {}
  const spatial = record.spatial_location || {}
  const disaster = record.disaster_type || {}
  const photo = record.photo_recognition || {}
  const recognized = photo.recognized_fields || {}
  const deformation = record.deformation_signs || {}
  const threats = record.threatened_objects || {}
  const conclusions = record.investigation_conclusions || {}
  return [
    { title: '基本现场信息', values: [
      { label: '记录编号', value: basic.record_id },
      { label: '报告人', value: basic.reporter },
      { label: '调查人', value: basic.investigator },
      { label: '巡查时间', value: basic.visit_time },
      { label: '行政区', value: basic.admin_area },
      { label: '现场描述', value: basic.narrative },
      { label: '资料来源', value: basic.is_simulated ? '随软件交付资料' : '现场业务记录' },
      { label: '数据来源', value: basic.data_source },
    ] },
    { title: '空间位置', values: [
      { label: '地点/地址', value: spatial.location },
      { label: '设备 GPS', value: spatial.gps },
      { label: 'GPS 状态', value: spatial.gps_status },
      { label: '报告原始坐标', value: spatial.reported_coordinates },
      { label: '坐标核验状态', value: spatial.coordinate_status },
      { label: '海拔（米）', value: spatial.elevation_m },
      { label: '隐患点', value: spatial.hazard_point_name || spatial.hazard_point_id },
      { label: '斜坡单元', value: spatial.slope_unit_id },
      { label: 'P6 映射', value: spatial.p6_mapping?.p6_slope_unit_id },
      { label: 'P6 映射状态', value: spatial.p6_mapping?.mapping_status },
    ] },
    { title: '灾害类型', values: [
      { label: '类型', value: disaster.type },
      { label: '类型编码', value: disaster.type_code },
      { label: '来源状态', value: disaster.verification_status },
    ] },
    { title: '照片识别', values: [
      { label: '执行状态', value: photo.status },
      { label: '核验状态', value: photo.verification_status },
      { label: '图片引用', value: photo.photo_refs },
      { label: '图像类型', value: recognized.image_type },
      { label: '识别灾害类型', value: recognized.disaster_type },
      { label: '识别变形迹象', value: recognized.deformation_signs },
      { label: '识别承灾体', value: recognized.threatened_object_types },
      { label: '新鲜程度', value: recognized.freshness },
      { label: '地灾阶段', value: recognized.stage },
      { label: '风险等级', value: recognized.risk_level },
      { label: '来源识别主张（未核验）', value: photo.source_claims },
    ] },
    { title: '变形迹象', values: [
      { label: '现场迹象', value: deformation.observations },
      { label: '量测状态', value: deformation.measurement_status },
      { label: '持续位移已确认', value: deformation.movement_confirmed },
      { label: '核验状态', value: deformation.verification_status },
    ] },
    { title: '受威胁对象', values: [
      { label: '对象类型', value: threats.types },
      { label: '户数', value: threats.households },
      { label: '人数', value: threats.people },
      { label: '房间数', value: threats.rooms },
      { label: '道路', value: threats.roads },
      { label: '道路名称', value: threats.road_name },
      { label: '道路等级', value: threats.road_grade },
      { label: '牲畜数', value: threats.livestock },
      { label: '财产损失估值', value: threats.asset_value },
      { label: '间接损失', value: threats.indirect_loss },
      { label: '对象详情', value: threats.details },
      { label: '来源状态', value: threats.verification_status },
    ] },
    { title: '调查结论', values: [
      { label: '结论摘要', value: conclusions.summary },
      { label: '成因', value: conclusions.causes },
      { label: '建议措施', value: conclusions.recommendations },
      { label: '来源状态', value: conclusions.verification_status },
    ] },
    { title: '待核实事项', values: [
      { label: '清单', value: record.items_to_verify },
    ] },
  ]
}

function formatFieldRecordValue(value) {
  if (value === null || value === undefined || value === '') return '未提供'
  if (Array.isArray(value)) {
    return value.length
      ? value.map((item) => (item && typeof item === 'object' ? item.label || JSON.stringify(item) : String(item))).join('；')
      : '无记录'
  }
  if (typeof value === 'object') return JSON.stringify(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  const statusLabels = {
    missing: '未提供',
    invalid: '格式无效',
    not_provided: '未提供',
    not_applicable: '不适用',
    pending: '待核验',
    pending_visual_model: '待视觉识别',
    pending_verification: '待人工核验',
    unverified: '未核验',
    verified: '已核验',
    source_reported: '来源记录',
    source_grounded: '原文锚定',
    not_configured: '未配置',
    completed_dify: 'Dify 已返回，待核验',
    simulated: '随附资料',
    candidate_unverified: '未核验候选',
  }
  return statusLabels[String(value).toLowerCase()] || String(value)
}
const taskPayloadReady = computed(() => {
  const event = fieldResult.value
  const task = decisionResult.value?.action_items?.[0]?.java_task_payload
  return !!event
    && event.source_kind === 'FIELD_REPORT'
    && event.is_simulated === false
    && String(event.admin_area || '').includes('宜昌市')
    && !!event.slope_unit_id
    && !!task?.unitId
    && String(task.unitId) === String(event.slope_unit_id)
    && Number(task.sourceType) === 2
    && !String(task.unitId).toUpperCase().startsWith('GOLD-')
})
const canSubmitFeedback = computed(() => [2, 3].includes(Number(taskDetail.value?.status)) && !!currentUserId.value)
const reportId = computed(() => {
  const associations = reportDraft.value?.associations || {}
  const id = associations.new_report_id && associations.new_report_id !== 'unknown'
    ? associations.new_report_id
    : associations.existing_report_ids?.[0]
  return id && id !== 'unknown' ? String(id) : ''
})
const goldReportId = computed(() => String(
  goldReportDraft.value?.report_id
  || goldReportDraft.value?.associations?.new_report_id
  || '',
))

function localDateTimeInput(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function javaDateTimeNow() {
  const date = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function toJavaDateTime(value) {
  if (!value) return null
  return value.length === 16 ? `${value.replace('T', ' ')}:00` : value.replace('T', ' ')
}

function onFieldPhotosChange(event) {
  fieldPhotos.value = Array.from(event.target.files || [])
}

function onFeedbackPhotosChange(event) {
  feedbackPhotos.value = Array.from(event.target.files || [])
}

function photoIdsFromResponse(response) {
  if (Array.isArray(response)) return response.map(String)
  if (Array.isArray(response?.data)) return response.data.map(String)
  return []
}

const A2_MAX_PHOTOS = 3
const A2_MAX_PHOTO_BYTES = 10 * 1024 * 1024
const A2_MAX_TOTAL_PHOTO_BYTES = A2_MAX_PHOTOS * A2_MAX_PHOTO_BYTES
const A2_IMAGE_MIME_BY_EXTENSION = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
}
const A2_IMAGE_EXTENSION_BY_MIME = Object.fromEntries(
  Object.entries(A2_IMAGE_MIME_BY_EXTENSION).map(([extension, mimeType]) => [mimeType, extension]),
)

function getA2PhotoMimeType(blob, filename) {
  const extension = filename?.match(/\.[^.]+$/)?.[0]?.toLowerCase() || ''
  const extensionMimeType = A2_IMAGE_MIME_BY_EXTENSION[extension]
  let mimeType = String(blob.type || '').split(';')[0].trim().toLowerCase()
  if (mimeType === 'image/jpg') mimeType = 'image/jpeg'
  if (!mimeType || mimeType === 'application/octet-stream') mimeType = extensionMimeType || ''
  if (!A2_IMAGE_EXTENSION_BY_MIME[mimeType]) return ''
  if (extensionMimeType && extensionMimeType !== mimeType) return ''
  return mimeType
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error || new Error('照片读取失败'))
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const separator = result.indexOf(',')
      if (separator < 0) return reject(new Error('照片编码失败'))
      resolve(result.slice(separator + 1))
    }
    reader.readAsDataURL(blob)
  })
}

async function buildA2PhotoUploads(photoRefs, sourceFiles) {
  if (photoRefs.length > A2_MAX_PHOTOS) {
    return { uploads: null, warning: 'A2 每次最多接收 ' + A2_MAX_PHOTOS + ' 张照片；OSS 引用仍会保留，视觉分析待处理。' }
  }

  const uploads = []
  let totalBytes = 0
  for (let index = 0; index < photoRefs.length; index += 1) {
    const reference = photoRefs[index]
    let blob = sourceFiles[index]
    let filename = blob?.name || ''
    if (!blob) {
      if (typeof reference !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(reference)) {
        return { uploads: null, warning: '现有照片引用不是可安全读取的 OSS ID；引用仍会保留，视觉分析待处理。' }
      }
      try {
        blob = await downloadFile(reference)
      } catch {
        return { uploads: null, warning: '无法通过当前登录态读取 OSS 照片；引用仍会保留，视觉分析待处理。' }
      }
      if (!(blob instanceof Blob)) {
        return { uploads: null, warning: 'OSS 下载未返回照片字节；引用仍会保留，视觉分析待处理。' }
      }
      const mimeType = getA2PhotoMimeType(blob, '')
      if (!mimeType) {
        return { uploads: null, warning: 'OSS 照片格式不受 A2 支持；引用仍会保留，视觉分析待处理。' }
      }
      filename = reference + A2_IMAGE_EXTENSION_BY_MIME[mimeType]
    }

    if (!(blob instanceof Blob) || blob.size === 0 || blob.size > A2_MAX_PHOTO_BYTES) {
      return { uploads: null, warning: 'A2 单张照片限制为 10 MiB；OSS 引用仍会保留，视觉分析待处理。' }
    }
    totalBytes += blob.size
    if (totalBytes > A2_MAX_TOTAL_PHOTO_BYTES) {
      return { uploads: null, warning: 'A2 照片总量超出限制；OSS 引用仍会保留，视觉分析待处理。' }
    }

    const mimeType = getA2PhotoMimeType(blob, filename)
    if (!mimeType) {
      return { uploads: null, warning: 'A2 仅支持 JPG、PNG、GIF、WebP 或 SVG 照片；OSS 引用仍会保留，视觉分析待处理。' }
    }
    if (!/\.[^.]+$/.test(filename)) {
      filename = (filename || ('field-photo-' + (index + 1))) + A2_IMAGE_EXTENSION_BY_MIME[mimeType]
    }
    try {
      uploads.push({
        index,
        reference,
        filename,
        mime_type: mimeType,
        content_base64: await blobToBase64(blob),
      })
    } catch {
      return { uploads: null, warning: '照片字节读取失败；OSS 引用仍会保留，视觉分析待处理。' }
    }
  }
  return { uploads, warning: '' }
}

function agentStatusLabel(status) {
  return ({
    implemented: '入口已接入',
    gold_adapter_implemented: '业务服务已接入',
    implemented_input_only: '证据组装已接入',
    draft_and_archive_adapter_implemented: '报告草案已接入',
    checking: '检测中',
  })[status] || status || '未知'
}

function agentDifyLabel(agentId) {
  if (!agentsLoaded.value || agentsError.value) return '配置未知'
  const apps = difyApps.value.filter((app) => app.agent_id === agentId)
  if (!apps.length) return '未登记 App'
  const configuredCount = apps.filter((app) => app.configured === true).length
  if (configuredCount === apps.length) return 'Key 已配'
  if (configuredCount > 0) return '部分 Key 未配'
  return 'Key 未配置'
}

function scenarioTitle(id) {
  return ({
    'GOLD-01': '现场巡查记录',
    'GOLD-02': '秭归市事件 · 告警处置与恢复观察',
    'GOLD-03': '恢复观察阶段',
  })[id] || '秭归市事件'
}

async function loadAgents() {
  try {
    const data = await getYichangAgents()
    agentStatus.value = data.agents || {}
    difyApps.value = Array.isArray(data.dify_apps) ? data.dify_apps : []
    a2DifyConfigured.value = difyApps.value.some((app) => app.agent_id === 'A2' && app.configured === true)
    agentsError.value = false
  } catch {
    agentsError.value = true
    difyApps.value = []
    a2DifyConfigured.value = false
  } finally {
    agentsLoaded.value = true
  }
}

async function loadGoldRecords({ keepResult = false } = {}) {
  goldReadbackLoading.value = true
  goldReadbackError.value = ''
  try {
    const current = await getYichangGoldRecords(scenarioId.value)
    const records = Array.isArray(current.records) ? current.records : []
    const related = scenarioId.value === 'GOLD-03'
      ? await getYichangGoldRecords('GOLD-02')
      : null
    const allRecords = [...records, ...(Array.isArray(related?.records) ? related.records : [])]
    const events = records.filter((record) => record.record_type === 'event')
    const eventRecord = events[events.length - 1]
    if (!eventRecord) {
      if (!keepResult) result.value = null
      goldActionDraft.value = emptyGoldAction()
      goldTaskId.value = ''
      goldTaskState.value = null
      goldReportDraft.value = null
      goldArchiveResult.value = null
      goldArchiveStatus.value = ''
      goldFeedbackStatus.value = ''
      goldReadbackStatus.value = '秭归市事件当前暂无已保存记录。'
      return
    }

    const event = eventRecord.payload || {}
    const traceId = event.trace_id
    const scoped = allRecords.filter((record) => (
      record.record_id === eventRecord.record_id || record.payload?.trace_id === traceId
    ))
    const latest = (type) => scoped.filter((record) => record.record_type === type).at(-1)
    const ragRecord = latest('rag_retrieval')
    const decisionRecord = latest('decision')
    const proposalRecord = latest('task_proposal')
    const taskRecord = latest('task')
    const feedbackRecords = scoped.filter((record) => record.record_type === 'feedback')
    const reportRecord = latest('report')
    const archiveRecord = latest('archive')
    const decision = decisionRecord?.payload || null
    const report = reportRecord?.payload || null
    const archive = archiveRecord?.payload || null
    goldActionDraft.value = {
      ...emptyGoldAction(),
      ...(taskRecord?.payload?.action || proposalRecord?.payload?.action || {}),
    }
    const restored = {
      status: 'persisted_records_loaded',
      scenario_id: scenarioId.value,
      trace_id: traceId,
      correlation_id: event.correlation_id,
      event_id: eventRecord.record_id,
      task_id: taskRecord?.record_id || null,
      report_id: reportRecord?.record_id || null,
      is_simulated: event.is_simulated === true,
      data_source: event.data_source,
      execution_engine: 'local',
      event,
      a2: scenarioId.value === 'GOLD-01' ? event : null,
      a3: scenarioId.value === 'GOLD-01' ? null : { ...event, monitoring: event.monitoring },
      rag: ragRecord ? { ...ragRecord.payload, record_id: ragRecord.record_id } : null,
      a4: decision,
      java_task: {
        status: taskRecord?.status || proposalRecord?.status || 'awaiting_human_approval',
        task_id: taskRecord?.record_id || null,
        created: !!taskRecord,
        execution_engine: 'local',
        formal_java_task_created: false,
      },
      task_proposal: proposalRecord?.payload || null,
      a5: report,
      evidence_archive: archive || { status: report?.archive_status || 'awaiting_report_and_archive_approval' },
      persisted_record_ids: scoped.map((record) => record.record_id),
      trace: [],
    }
    if (!keepResult) result.value = restored
    goldTaskId.value = taskRecord?.record_id || ''
    goldTaskState.value = taskRecord?.payload || null
    goldFeedbackStatus.value = feedbackRecords.length
      ? `已读取 ${feedbackRecords.length} 条处置反馈记录。`
      : ''
    goldReportDraft.value = report
    goldReportConclusion.value = report?.reviewer_conclusion || ''
    goldReportApproved.value = report?.review_status === 'approved'
    goldArchiveApproved.value = archive?.status === 'archived_demo_local'
    goldArchiveResult.value = archive
    const savedArchiveStatus = archive?.status || report?.archive_status || ''
    goldArchiveStatus.value = savedArchiveStatus ? '复盘报告已归档至本地事件资料。' : ''
    goldReadbackStatus.value = `已读取秭归市事件及 ${scoped.length} 条关联业务记录。`
  } catch (error) {
    goldReadbackError.value = '事件记录暂时无法读取，请检查服务状态后重试。'
  } finally {
    goldReadbackLoading.value = false
  }
}

async function runScenario() {
  running.value = true
  runError.value = ''
  result.value = null
  goldTaskId.value = ''
  goldTaskState.value = null
  goldTaskError.value = ''
  goldFeedbackText.value = ''
  goldFeedbackStatus.value = ''
  goldFeedbackError.value = ''
  goldReportDraft.value = null
  goldReportConclusion.value = ''
  goldReportApproved.value = false
  goldArchiveApproved.value = false
  goldArchiveResult.value = null
  goldArchiveStatus.value = ''
  goldArchiveError.value = ''
  goldVerifyStatus.value = ''
  try {
    result.value = await runYichangGold(scenarioId.value)
    goldTaskId.value = result.value.java_task?.task_id || ''
    goldTaskState.value = result.value.java_task || null
    await loadGoldRecords({ keepResult: true })
  } catch {
    runError.value = '秭归市事件研判暂未完成，请检查服务状态后重试。'
  } finally {
    running.value = false
  }
}

async function approveGoldTask() {
  if (!result.value?.task_proposal || !goldReviewerId.value || !goldTaskActionReady.value || goldTaskId.value) return
  goldTaskRunning.value = true
  goldTaskError.value = ''
  try {
    const response = await confirmYichangGoldTask({
      event_id: result.value.event_id,
      proposal_id: result.value.task_proposal.proposal_id,
      action: { ...goldActionDraft.value },
      is_simulated: true,
    }, goldReviewerId.value)
    goldTaskId.value = response.task_id || ''
    goldTaskState.value = response.task || response
    goldFeedbackStatus.value = ''
    await loadGoldRecords({ keepResult: true })
  } catch {
    goldTaskError.value = '处置任务审核暂未完成，请检查事件资料后重试。'
  } finally {
    goldTaskRunning.value = false
  }
}

async function submitGoldFeedback() {
  if (!goldTaskId.value || !result.value?.event_id || !goldReviewerId.value || !goldFeedbackText.value) return
  goldFeedbackRunning.value = true
  goldFeedbackError.value = ''
  goldFeedbackStatus.value = ''
  try {
    const response = await submitYichangGoldFeedback(goldTaskId.value, {
      event_id: result.value.event_id,
      text: goldFeedbackText.value,
      data_source: 'manual_gold_field_feedback',
      is_simulated: true,
    }, goldReviewerId.value)
    goldTaskState.value = { ...(goldTaskState.value || {}), status: response.task_status || response.status }
    goldFeedbackStatus.value = '处置反馈已保存至当前事件记录。'
    await loadGoldRecords({ keepResult: true })
    goldReportDraft.value = null
    goldArchiveResult.value = null
    goldReportApproved.value = false
    goldArchiveApproved.value = false
  } catch {
    goldFeedbackError.value = '处置反馈暂未保存，请检查服务状态后重试。'
  } finally {
    goldFeedbackRunning.value = false
  }
}

async function buildGoldReportDraft() {
  if (!result.value?.event_id) return
  goldReportRunning.value = true
  goldArchiveError.value = ''
  goldReportDraft.value = null
  goldArchiveResult.value = null
  goldArchiveStatus.value = ''
  goldVerifyStatus.value = ''
  try {
    goldReportDraft.value = await buildYichangReportDraft({
      event: { event_id: result.value.event_id },
      user: goldReviewerId.value || result.value.event_id,
      query: '根据已保存的秭归市事件、任务和现场反馈整理复盘报告，保留资料来源、核验状态与缺失项。',
    })
    goldReportConclusion.value = ''
    goldReportApproved.value = false
    goldArchiveApproved.value = false
    await loadGoldRecords({ keepResult: true })
  } catch {
    goldArchiveError.value = '处置复盘报告暂未生成，请检查服务状态后重试。'
  } finally {
    goldReportRunning.value = false
  }
}

async function archiveGoldReport() {
  if (!goldReportDraft.value || !goldReviewerId.value || !goldReportApproved.value || !goldArchiveApproved.value) return
  goldArchiveRunning.value = true
  goldArchiveError.value = ''
  goldArchiveStatus.value = ''
  try {
    const report = JSON.parse(JSON.stringify(goldReportDraft.value))
    const conclusion = goldReportConclusion.value.trim()
    report.sections = {
      ...(report.sections || {}),
      review_conclusion: conclusion || report.sections?.review_conclusion || 'unknown',
    }
    if (conclusion) {
      report.report_text = [report.report_text, '## 审核补充结论', conclusion].filter(Boolean).join('\n\n')
    }
    report.reviewer_conclusion = conclusion
    const response = await archiveYichangReport(report, goldReviewerId.value)
    goldArchiveResult.value = response
    goldReportDraft.value = {
      ...report,
      status: response.status,
      review_status: 'approved',
      archive_status: response.status,
    }
    goldArchiveStatus.value = '复盘报告已归档至秭归市事件资料。'
    await loadGoldRecords({ keepResult: true })
  } catch {
    goldArchiveError.value = '复盘报告审核归档暂未完成，请检查服务状态后重试。'
  } finally {
    goldArchiveRunning.value = false
  }
}

async function verifyGoldReport() {
  if (!goldReportId.value || !goldArchiveResult.value?.document_id) return
  goldVerifyRunning.value = true
  goldVerifyStatus.value = ''
  goldArchiveError.value = ''
  try {
    const response = await queryYichang(
      '请根据报告编号回查秭归市事件复盘记录。',
    )
    const exactMatch = (response.evidence || []).some((item) => (
      item.report_id === goldReportId.value
      || item.file_name === 'demo-evidence:' + goldReportId.value
    ))
    goldVerifyStatus.value = exactMatch
      ? '已在事件资料中检索到对应复盘报告。'
      : '报告未能在事件资料中精确检索到。'
  } catch {
    goldArchiveError.value = '复盘报告检索暂未完成，请稍后重试。'
  } finally {
    goldVerifyRunning.value = false
  }
}

async function askQuestion() {
  asking.value = true
  qaError.value = ''
  qaResult.value = null
  try {
    qaResult.value = await queryYichang(question.value)
  } catch (error) {
    qaError.value = error.message || '宜昌知识问答失败'
  } finally {
    asking.value = false
  }
}

async function runFieldAnalysis() {
  fieldRunning.value = true
  fieldError.value = ''
  fieldResult.value = null
  decisionResult.value = null
  taskApproval.value = false
  taskId.value = ''
  taskDetail.value = null
  taskFeedbacks.value = []
  reportDraft.value = null
  archiveResult.value = null
  let photoRefs = fieldForm.value.photoRefs.split(/\r?\n/).map((value) => value.trim()).filter(Boolean)
  const sourceFiles = photoRefs.map(() => null)
  try {
    if (fieldPhotos.value.length && fieldForm.value.isSimulated) {
      const localRefs = fieldPhotos.value.map((file) => 'simulated-local-file:' + file.name)
      photoRefs = [...photoRefs, ...localRefs]
      sourceFiles.push(...fieldPhotos.value)
    } else if (fieldPhotos.value.length) {
      const uploaded = await uploadTaskPhotos(null, fieldPhotos.value)
      const ids = photoIdsFromResponse(uploaded)
      if (ids.length !== fieldPhotos.value.length) throw new Error('照片 OSS 上传未完整返回 ID，已停止 A2 分析')
      photoRefs = [...photoRefs, ...ids]
      sourceFiles.push(...fieldPhotos.value)
    }

    if (photoRefs.length && (!agentsLoaded.value || agentsError.value)) await loadAgents()
    let photoUploads = null
    let photoUploadWarning = ''
    if (a2DifyConfigured.value) {
      const prepared = await buildA2PhotoUploads(photoRefs, sourceFiles)
      photoUploads = prepared.uploads
      photoUploadWarning = prepared.warning
    } else if (agentsError.value && photoRefs.length) {
      photoUploadWarning = 'A2 配置状态未能确认；本次继续保存照片引用，视觉分析待处理。'
    }

    const gps = fieldForm.value.latitude !== '' && fieldForm.value.longitude !== ''
      ? { lat: Number(fieldForm.value.latitude), lon: Number(fieldForm.value.longitude) }
      : undefined
    const county = fieldForm.value.county.trim()
    const p6SlopeUnitId = fieldForm.value.p6SlopeUnitId.trim()
    const p6MappingConfirmed = !!p6SlopeUnitId && fieldForm.value.p6MappingConfirmed
    const payload = {
      admin_area: '宜昌市' + (county ? ' / ' + county : ''),
      slope_unit_id: fieldForm.value.slopeUnitId || null,
      p6_slope_unit_id: p6SlopeUnitId || null,
      spatial_ref_status: p6MappingConfirmed
        ? 'HUMAN_CONFIRMED'
        : (p6SlopeUnitId ? 'ID_REFERENCE_ONLY_COORDINATE_UNVERIFIED' : null),
      spatial_object_source: p6SlopeUnitId
        ? (p6MappingConfirmed ? 'manual_field_reporter_confirmation' : 'manual_field_reporter_selection_unconfirmed')
        : null,
      hazard_point_id: fieldForm.value.hazardPointId || null,
      visit_time: toJavaDateTime(fieldForm.value.visitTime),
      text: fieldForm.value.narrative,
      photo_refs: photoRefs,
      ...(photoUploads ? { photo_uploads: photoUploads } : {}),
      ...(gps ? { gps } : {}),
      is_simulated: fieldForm.value.isSimulated,
      data_source: fieldForm.value.isSimulated ? 'manual_gold_simulation' : 'yichang_field_report',
    }
    fieldResult.value = await processYichangFieldReport(payload)
    if (photoUploadWarning) fieldError.value = photoUploadWarning
  } catch (error) {
    fieldError.value = error.message || 'A2 现场输入处理失败'
  } finally {
    fieldRunning.value = false
  }
}
async function runFieldDecision() {
  decisionRunning.value = true
  decisionError.value = ''
  decisionResult.value = null
  const source = fieldResult.value
  const event = {
    ...source,
    event_type: '现场险情核查',
    description: source.field_report?.narrative || '',
    field_notes: source.field_report?.narrative || '',
    location: source.admin_area || '宜昌市（具体位置待核实）',
  }
  try {
    decisionResult.value = await runYichangDecision(event)
  } catch (error) {
    decisionError.value = error.message || 'A4 研判失败'
  } finally {
    decisionRunning.value = false
  }
}

function taskStatusLabel(status) {
  return ({ 1: '未推送', 2: '未核查', 3: '核查中', 4: '已关闭', 5: '已反馈', 6: '技术协查中', 7: '已过期' })[Number(status)] || '状态待读取'
}

async function refreshJavaTask() {
  if (!taskId.value) return
  taskRefreshing.value = true
  taskError.value = ''
  try {
    taskDetail.value = await getTaskDetail(taskId.value)
    taskFeedbacks.value = await getTaskFeedbacks(taskId.value)
  } catch (error) {
    taskError.value = error.message || 'Java 任务或反馈读取失败'
  } finally {
    taskRefreshing.value = false
  }
}

async function createJavaTask() {
  if (!taskPayloadReady.value || !taskApproval.value) return
  creatingTask.value = true
  taskError.value = ''
  try {
    const action = decisionResult.value.action_items[0]
    const correlationId = fieldResult.value.correlation_id
    const response = await addTaskDistList({
      ...action.java_task_payload,
      textRecord: fieldResult.value.field_report?.narrative || '',
      remark: `GeoGuard 宜昌事件关联 ID：${correlationId}`,
    })
    const createdId = response?.data ?? response?.id ?? response
    if (!createdId) throw new Error('Java 接口未返回任务 ID')
    taskId.value = String(createdId)
    await refreshJavaTask()
    taskApproval.value = false
  } catch (error) {
    taskError.value = error.message || 'Java 核查任务创建失败'
  } finally {
    creatingTask.value = false
  }
}

async function submitJavaFeedback() {
  feedbackRunning.value = true
  feedbackError.value = ''
  feedbackStatus.value = ''
  try {
    if (!currentUserId.value) throw new Error('当前登录用户缺少 Java 用户 ID')
    const name = currentUser.value.userName || currentUser.value.nickName || currentUser.value.name
    if (!name) throw new Error('当前登录账户未返回姓名，不能代填现场反馈人')
    if (feedbackPhotos.value.length < 2) throw new Error('Java 任务反馈至少需要 2 张现场照片')
    const lat = Number(feedbackForm.value.latitude)
    const lon = Number(feedbackForm.value.longitude)
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error('请输入本次现场核查的有效 GPS 坐标')
    const uploaded = await uploadTaskPhotos(taskId.value, feedbackPhotos.value)
    const photos = photoIdsFromResponse(uploaded)
    if (photos.length < 2) throw new Error('反馈照片 OSS 上传不足 2 张，已停止提交')
    const now = javaDateTimeNow()
    await submitTaskFeedback({
      taskId: Number(taskId.value),
      inspectorId: Number(currentUserId.value),
      inspectorName: name,
      inspectorPhone: currentUser.value.phonenumber || currentUser.value.phoneNumber || '',
      checkInTime: now,
      checkInCenter: `POINT(${lon} ${lat})`,
      checkCenterLocation: `${lat}, ${lon}`,
      photos,
      textRecord: feedbackForm.value.text.trim(),
      submitTime: now,
      status: 5,
    })
    await refreshJavaTask()
    const confirmed = taskFeedbacks.value.some((item) => String(item.taskId) === taskId.value
      && String(item.textRecord || '').includes(feedbackForm.value.text.trim()))
    feedbackStatus.value = confirmed ? 'Java 反馈已写入并回读确认。' : '接口已提交；回读记录尚未匹配，请刷新核对。'
    feedbackPhotos.value = []
  } catch (error) {
    feedbackError.value = error.message || '现场反馈提交失败'
  } finally {
    feedbackRunning.value = false
  }
}

async function createReportDraft() {
  reportRunning.value = true
  archiveError.value = ''
  reportDraft.value = null
  try {
    if (taskId.value) await refreshJavaTask()
    const persistedTask = taskDetail.value || {}
    const source = fieldResult.value
    const correlation = String(persistedTask.remark || '').match(/GeoGuard.*?ID[：:]\s*([A-Za-z0-9_-]+)/)?.[1]
    const event = source ? {
      ...source,
      event_type: '现场险情核查',
      description: source.field_report?.narrative || '',
    } : {
      ...(persistedTask.warningEventId ? { event_id: persistedTask.warningEventId } : {}),
      source_kind: String(persistedTask.taskSource || '').includes('宜昌A4人工审核') ? 'FIELD_REPORT' : 'unknown',
      ...(correlation ? { correlation_id: correlation } : {}),
      admin_area: persistedTask.detailedAddress || 'unknown',
      slope_unit_id: persistedTask.unitId || 'unknown',
      event_type: persistedTask.taskType || 'unknown',
      description: persistedTask.textRecord || persistedTask.inspectionSuggestion || '',
      data_source: 'java_task_readback',
      is_simulated: /GOLD-/i.test(`${persistedTask.remark || ''} ${persistedTask.taskSource || ''}`),
    }
    const attachments = (fieldResult.value?.field_report?.photo_refs || []).map((fileId) => ({
      file_id: fileId,
      data_source: source.data_source,
      is_simulated: source.is_simulated,
    }))
    reportDraft.value = await buildYichangReportDraft({
      event,
      tasks: taskDetail.value ? [taskDetail.value] : [],
      feedback: taskFeedbacks.value,
      risk_review: decisionResult.value,
      attachments,
    })
    reviewConclusion.value = ''
    reportApproved.value = false
    archiveApproved.value = false
    archiveResult.value = null
    archiveStatus.value = ''
  } catch (error) {
    archiveError.value = error.message || 'A5 报告草案生成失败'
  } finally {
    reportRunning.value = false
  }
}

async function archiveReport() {
  if (!reportDraft.value || !reportApproved.value || !archiveApproved.value || !reportId.value) return
  archiving.value = true
  archiveError.value = ''
  archiveStatus.value = ''
  try {
    const report = JSON.parse(JSON.stringify(reportDraft.value))
    if (reviewConclusion.value) report.sections.review_conclusion = reviewConclusion.value
    archiveResult.value = await archiveYichangReport(report)
    archiveStatus.value = `${archiveResult.value.status}${archiveResult.value.document_id ? ` · 文档 ${archiveResult.value.document_id}` : ''}`
  } catch (error) {
    archiveError.value = error.message || '证据库归档失败'
  } finally {
    archiving.value = false
  }
}

async function verifyArchivedReport() {
  qaVerifying.value = true
  qaArchiveFound.value = null
  qaError.value = ''
  try {
    qaResult.value = await queryYichang('请检索宜昌地质灾害事件复盘报告，并摘要报告中的事件事实、处置反馈和复核结论。')
    qaArchiveFound.value = qaResult.value.evidence?.some((item) => item.file_name === archiveResult.value.file_name) || false
  } catch (error) {
    qaError.value = error.message || 'A1 证据回检失败'
  } finally {
    qaVerifying.value = false
  }
}

onMounted(() => {
  loadAgents()
  loadGoldRecords()
})
</script>

<style lang="less" scoped>
.yichang-panel {
  margin: 0 0 24px;
  padding: 22px;
  border: 1px solid var(--gg-border-quiet, #e2e8f0);
  border-radius: 14px;
  background: var(--gg-surface, #fff);
  color: var(--gg-text-primary, #222527);
  box-shadow: 0 8px 24px rgba(28, 48, 75, 0.04);
}
.panel-heading,
.result-heading,
.run-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.eyebrow {
  color: #2887a0;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1px;
}
h2 {
  margin: 5px 0;
  font-size: 20px;
}
.panel-heading p,
.result-heading p,
.qa-box p,
.simulation-note {
  margin: 5px 0 0;
  color: var(--gg-text-secondary, #617185);
  font-size: 12px;
  line-height: 1.6;
}
.simulated-pill {
  flex-shrink: 0;
  padding: 6px 9px;
  border-radius: 999px;
  background: #fff4df;
  color: #946214;
  font-size: 11px;
  font-weight: 600;
}
.agent-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 9px;
  margin: 17px 0;
}
.agent-card {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--gg-border-quiet, #e2e8f0);
  border-radius: 9px;
  background: var(--gg-page-bg, #f8fafc);
}
.agent-id {
  display: grid;
  width: 27px;
  height: 27px;
  flex-shrink: 0;
  place-items: center;
  border-radius: 8px;
  background: #e8f4f7;
  color: #247d91;
  font-size: 11px;
  font-weight: 700;
}
.agent-card div { min-width: 0; }
.agent-card strong,
.agent-card small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-card strong { font-size: 11px; }
.agent-card small { margin-top: 3px; color: var(--gg-text-secondary, #718398); font-size: 10px; }
.run-row { justify-content: flex-start; flex-wrap: wrap; }
.run-row label { color: var(--gg-text-secondary, #617185); font-size: 12px; }
select,
.qa-box input {
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid var(--gg-border-quiet, #d9e2ec);
  border-radius: 7px;
  background: #fff;
  color: var(--gg-text-primary, #222527);
  font-size: 12px;
}
select { min-width: 235px; }
button {
  min-height: 36px;
  padding: 0 14px;
  border: 0;
  border-radius: 7px;
  background: #248aa0;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
button:disabled { cursor: not-allowed; opacity: 0.55; }
.inline-error { color: #b8473b; font-size: 11px; }
.simulation-note { margin: 11px 0 0; }
.run-result,
.qa-box,
.field-flow,
.flow-result {
  margin-top: 16px;
  padding: 15px;
  border: 1px solid var(--gg-border-quiet, #e2e8f0);
  border-radius: 10px;
  background: var(--gg-page-bg, #fafbfd);
}
.field-flow { padding: 17px; }
.flow-heading,
.approval-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.flow-heading h3 { margin: 0; font-size: 14px; }
.flow-heading p { margin: 5px 0 0; color: var(--gg-text-secondary, #617185); font-size: 11px; line-height: 1.5; }
.flow-state { color: #247d91; font-size: 11px; font-weight: 700; }
.field-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 13px; }
.field-form label,
.wide-field { display: grid; gap: 5px; color: var(--gg-text-secondary, #617185); font-size: 11px; }
.field-form input:not([type='checkbox']),
.field-form textarea,
.flow-result textarea {
  width: 100%; min-width: 0; padding: 8px 9px; border: 1px solid var(--gg-border-quiet, #d9e2ec);
  border-radius: 7px; background: #fff; color: var(--gg-text-primary, #222527); font: inherit; font-size: 12px;
}
.field-form input[type='file'] { padding: 6px; }
.field-form textarea,
.flow-result textarea { resize: vertical; line-height: 1.5; }
.wide-field { grid-column: 1 / -1; }
.check-field { display: flex !important; align-items: center; gap: 7px !important; line-height: 1.5; }
.check-field input { flex: 0 0 auto; }
.field-form > button { justify-self: start; }
.flow-result { padding: 13px; background: #fff; }
.flow-result > p { color: var(--gg-text-secondary, #617185); font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.flow-result > button { margin-top: 6px; }
.finding-list { display: grid; gap: 6px; padding-left: 18px; color: var(--gg-text-primary, #344256); font-size: 11px; }
.finding-list small { color: var(--gg-text-secondary, #718398); }
.model-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; margin-top: 11px; }
.model-grid div { padding: 8px; border-radius: 7px; background: var(--gg-page-bg, #f8fafc); }
.model-grid small,
.model-grid strong { display: block; overflow-wrap: anywhere; }
.model-grid small { color: var(--gg-text-secondary, #718398); font-size: 10px; }
.model-grid strong { margin-top: 4px; font-size: 11px; }
.recommendation { padding: 9px; border-left: 3px solid #248aa0; background: #f3fafb; white-space: pre-wrap; }
.approval-row { justify-content: flex-start; margin-top: 10px; }
.approval-row .check-field { max-width: 100%; }
.secondary-button { background: #e9eff4; color: #36526b; }
.persisted-note { color: #247d5a !important; font-weight: 600; }
.muted-copy { color: var(--gg-text-secondary, #718398) !important; }
.draft-preview { max-height: 250px; overflow: auto; padding: 10px; border-radius: 7px; background: #f2f5f8; color: #344256; font-size: 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.task-lookup { display: flex; align-items: end; gap: 9px; margin-top: 14px; }
.task-lookup label { display: grid; min-width: min(100%, 300px); gap: 5px; color: var(--gg-text-secondary, #617185); font-size: 11px; }
.task-lookup input { min-height: 36px; padding: 0 9px; border: 1px solid var(--gg-border-quiet, #d9e2ec); border-radius: 7px; font-size: 12px; }
.monitor-series { margin-top: 12px; padding: 10px; border: 1px solid var(--gg-border-quiet, #e2e8f0); border-radius: 8px; background: #fff; }
.monitor-series summary { cursor: pointer; color: #247d91; font-size: 11px; font-weight: 700; }
.monitor-series p { color: var(--gg-text-secondary, #718398); font-size: 10px; }
.series-scroll { overflow-x: auto; }
.series-scroll table { width: 100%; min-width: 780px; border-collapse: collapse; font-size: 10px; }
.series-scroll th,
.series-scroll td { padding: 6px; border-bottom: 1px solid var(--gg-border-quiet, #e2e8f0); text-align: left; white-space: nowrap; }
.series-scroll th { color: var(--gg-text-secondary, #718398); font-weight: 600; }
.result-heading p { word-break: break-all; }
.result-status { font-size: 13px; font-weight: 700; }
.result-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 13px;
}
.result-grid div { padding: 9px; border-radius: 7px; background: #fff; }
.result-grid small,
.result-grid strong { display: block; }
.result-grid small { color: var(--gg-text-secondary, #718398); font-size: 10px; }
.result-grid strong { margin-top: 4px; font-size: 11px; overflow-wrap: anywhere; }
.field-investigation-card {
  margin-top: 14px;
  padding: 13px;
  border: 1px solid var(--gg-border-quiet, #e2e8f0);
  border-radius: 9px;
  background: var(--gg-surface, #fff);
}
.field-record-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin-top: 11px; }
.field-record-section { min-width: 0; padding: 10px; border: 1px solid var(--gg-border-quiet, #e2e8f0); border-radius: 8px; background: var(--gg-page-bg, #f8fafc); }
.field-record-section h4 { margin: 0 0 8px; color: var(--gg-text-primary, #344256); font-size: 11px; }
.field-record-section dl { display: grid; gap: 6px; margin: 0; }
.field-record-section dl > div { display: grid; grid-template-columns: minmax(75px, 0.42fr) minmax(0, 1fr); gap: 8px; }
.field-record-section dt { color: var(--gg-text-secondary, #718398); font-size: 10px; }
.field-record-section dd { min-width: 0; margin: 0; color: var(--gg-text-primary, #344256); font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; white-space: pre-wrap; }
.trace-list { display: grid; gap: 5px; margin: 12px 0 0; padding-left: 20px; }
.trace-list li { display: flex; justify-content: space-between; gap: 12px; color: var(--gg-text-secondary, #617185); font-size: 10px; }
.trace-list b { color: var(--gg-text-primary, #344256); font-weight: 600; }
.qa-box { display: grid; grid-template-columns: minmax(180px, 0.8fr) minmax(260px, 1.2fr); gap: 12px; align-items: center; }
.qa-box h3 { margin: 0; font-size: 13px; }
.qa-box form { display: flex; gap: 7px; }
.qa-box input { min-width: 0; flex: 1; }
.qa-answer { grid-column: 1 / -1; padding-top: 8px; border-top: 1px solid var(--gg-border-quiet, #e2e8f0); }
.qa-answer p { white-space: pre-wrap; }
.qa-answer ul { display: grid; gap: 5px; margin: 9px 0 0; padding-left: 18px; color: var(--gg-text-secondary, #617185); font-size: 11px; }
.error-message { margin: 10px 0 0; color: #b8473b; font-size: 12px; }
@media (max-width: 900px) {
  .agent-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .result-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .field-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .model-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .field-record-grid { grid-template-columns: 1fr; }
  .qa-box { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .yichang-panel { padding: 15px; }
  .panel-heading { align-items: flex-start; }
  .agent-grid { grid-template-columns: 1fr; }
  .run-row { align-items: stretch; }
  .run-row label { width: 100%; }
  select { width: 100%; }
  .result-grid { grid-template-columns: 1fr; }
  .field-form { grid-template-columns: 1fr; }
  .field-form .wide-field { grid-column: 1; }
  .model-grid { grid-template-columns: 1fr 1fr; }
  .field-flow { padding: 13px; }
  .task-lookup { align-items: stretch; flex-direction: column; }
  .task-lookup label { min-width: 0; }
  .approval-row > button { width: 100%; }
  .qa-box form { flex-direction: column; }
}
</style>
