<template>
  <article class="disposal-plan-card">
    <header>
      <div>
        <span class="eyebrow">A4 · 应急调查处置意见书</span>
        <h3>{{ eventName }}</h3>
      </div>
      <span class="status-tag">待人工审核</span>
    </header>
    <div class="plan-facts">
      <div><span>风险等级</span><strong>{{ riskLevel }}</strong></div>
      <div><span>斜坡单元</span><strong>{{ slopeUnitId || '待关联' }}</strong></div>
      <div><span>处置任务</span><strong>8 个责任人任务位</strong></div>
    </div>
    <p>A4 结构化处置建议输出待接口联调。分项措施、责任部门、负责人、执行期限与验收要求先在任务派发页留位。</p>
    <button type="button" @click="onApprove">模拟审核通过，进入任务派发</button>
    <small>本机演示审核，不写入后端意见书或审批记录。</small>
  </article>
</template>

<script setup>
defineProps({
  eventName: { type: String, default: '当前事件' },
  riskLevel: { type: String, default: '--' },
  slopeUnitId: { type: String, default: '' },
  onApprove: { type: Function, default: () => {} },
})
</script>

<style scoped lang="less">
.disposal-plan-card { padding: 13px; border: 1px solid #dcecff; border-radius: 12px; background: #fff; color: #383c41; }
header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.eyebrow { color: #6481a2; font-size: 10px; }
h3 { margin: 4px 0 0; font-size: 13px; line-height: 1.45; }
.status-tag { flex: none; padding: 3px 7px; border-radius: 6px; color: #b67616; background: #fff4df; font-size: 10px; }
.plan-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; margin-top: 10px; }
.plan-facts div { min-width: 0; padding: 7px; border-radius: 7px; background: #f3f8ff; }
.plan-facts span, .plan-facts strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-facts span { color: #8494a8; font-size: 9px; }
.plan-facts strong { margin-top: 4px; color: #1479e6; font-size: 10px; }
p { margin: 10px 0; color: #617185; font-size: 11px; line-height: 1.55; }
button { width: 100%; min-height: 34px; border: 0; border-radius: 8px; background: #0879e8; color: #fff; font-size: 11px; font-weight: 700; cursor: pointer; }
small { display: block; margin-top: 6px; color: #9aa6b4; font-size: 9px; text-align: center; }
</style>
