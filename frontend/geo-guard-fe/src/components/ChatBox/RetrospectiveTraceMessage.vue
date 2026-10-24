<template>
  <div class="retrospective-trace">
    <p class="trace-intro">
      我将基于 <strong>{{ eventName }}</strong> 当前事件信息，结合随软件交付的秭归市事件资料，整理处置经过、记录来源并形成复盘报告：
    </p>
    <div class="trace-source">当前事件信息 · 秭归市事件处置资料 · 记录来源可追溯</div>

    <section v-for="(step, index) in steps" :key="step.title" class="trace-step">
      <button class="trace-step-heading" type="button" @click="toggle(index)" :aria-expanded="openSteps.has(index)">
        <span class="trace-check" aria-hidden="true">✓</span>
        <span>{{ step.title }}</span>
        <span class="trace-state">已整理</span>
        <span class="trace-chevron" :class="{ open: openSteps.has(index) }" aria-hidden="true">⌄</span>
      </button>
      <ul v-if="openSteps.has(index)" class="trace-details">
        <li v-for="detail in step.details" :key="detail.label">
          <strong>{{ detail.label }}：</strong>{{ detail.value }}
        </li>
      </ul>
    </section>

    <p class="trace-summary">
      当前页面已形成可下载的复盘报告内容；报告尚未写入事件审核记录，请在协同处置中心完成审核与归档。
    </p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  eventName: { type: String, default: '秭归市事件' },
  eventId: { type: String, default: '--' },
  eventTime: { type: String, default: '--' },
  location: { type: String, default: '--' },
})

const openSteps = ref(new Set([0, 1, 2]))
const steps = computed(() => [
  {
      title: '已关联当前事件信息',
    details: [
      { label: '主事件', value: props.eventName },
      { label: '事件编号', value: props.eventId },
      { label: '时间与位置', value: `${props.eventTime} · ${props.location}` },
      { label: '关联资料', value: '秭归市事件监测与处置资料' },
    ],
  },
  {
      title: '已归集事件处置记录',
    details: [
      { label: '随附资料', value: '调查记录、处置意见、4项任务、6条反馈和4条任务复核' },
      { label: '数据范围', value: '监测数值来自历史时片，不作为当前事件实时监测值' },
      { label: '待接入资料', value: '当前事件的正式调查报告、监测时序、任务回执和审核记录' },
    ],
  },
  {
      title: '已整理处置复盘报告',
    details: [
      { label: '异常与恢复', value: '按异常发现、恢复观察两个阶段整理变化记录' },
      { label: '报告内容', value: '事件概况、处置过程、专业分析、综合评价、问题原因、改进建议、复盘结论' },
      { label: '报告状态', value: '当前页面可下载；尚未写入事件审核记录' },
    ],
  },
])

function toggle(index) {
  const next = new Set(openSteps.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  openSteps.value = next
}
</script>

<style scoped>
.retrospective-trace{width:100%;padding:0 2px 8px;color:#354a62;font-size:13px;line-height:1.65}
.trace-intro{margin:0 0 8px;color:#354a62;line-height:1.75}
.trace-intro strong{color:#087cff}
.trace-source{display:inline-flex;margin:0 0 12px;padding:3px 9px;border:1px solid #dbe9fb;border-radius:14px;background:#f4f8ff;color:#56708f;font-size:11px}
.trace-step{margin:0 0 10px}
.trace-step-heading{display:flex;width:100%;align-items:center;gap:9px;padding:10px 12px;border:1px solid #dce7f6;border-radius:10px;background:#f4f8ff;color:#087cff;text-align:left;font:inherit;cursor:pointer}
.trace-check{display:grid;width:19px;height:19px;flex:none;place-items:center;border:1px solid #1685ff;border-radius:50%;font-size:12px;font-weight:700}
.trace-state{margin-left:auto;color:#788ba5;font-size:11px}
.trace-chevron{color:#8795a8;font-size:17px;transform:rotate(0);transition:transform .16s ease}
.trace-chevron.open{transform:rotate(180deg)}
.trace-details{display:grid;gap:8px;margin:10px 0 15px;padding:0 10px 0 29px;color:#75808f;list-style:disc}
.trace-details li{padding-left:1px;overflow-wrap:anywhere}
.trace-details strong{color:#303b49}
.trace-summary{margin:16px 0 0;color:#394454;line-height:1.8}
.trace-summary strong{color:#e78a20}
</style>
