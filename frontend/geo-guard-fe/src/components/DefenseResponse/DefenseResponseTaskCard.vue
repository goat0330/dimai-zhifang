<template>
  <article class="dr-task-card" :class="{ 'dr-task-selected': selected }" @click="$emit('select', task.id)">
    <span class="dr-task-ribbon" :class="'dr-status-'+task.status">{{ statusLabel }}</span>
    <div class="dr-task-head">
      <div class="dr-task-icon"><img :src="task.icon" alt="" /></div>
      <div class="dr-task-title-group">
        <h3>{{ task.label }}</h3>
        <span class="dr-task-subline">{{ task.owner }} · {{ statusLabel }}</span>
      </div>
    </div>
    <div class="dr-task-reporter" v-if="task.reporter || task.remark">
      <strong v-if="task.reporter">上报人员：{{ task.reporter }}</strong>
      <span v-if="task.remark">{{ task.remark }}</span>
    </div>
    <p v-else class="dr-no-report">暂无上报记录</p>
    <div class="dr-task-description" :title="task.description">{{ task.description || '暂无任务说明' }}</div>
    <div class="dr-task-feedback" v-if="task.photos?.length || task.remark">
      <span v-if="task.photos?.length">现场照片：</span>
      <div class="dr-task-photos" v-if="task.photos?.length">
        <button v-for="(photo, i) in task.photos" :key="i" type="button" @click.stop="$emit('preview-photo', photo)">
          <img v-if="typeof photo === 'string' && photo.startsWith('data:') || typeof photo === 'string' && photo.startsWith('http') || typeof photo === 'string' && photo.startsWith('blob:')" :src="photo" alt="现场照片" />
          <span v-else>照片 {{ i + 1 }}</span>
        </button>
      </div>
    </div>
    <footer class="dr-task-actions">
      <button type="button" :disabled="archived || task.status !== 'pending'" @click.stop="$emit('push', task.id)">↗ 推送</button>
      <button type="button" :disabled="archived || ['feedback', 'verified', 'closed'].includes(task.status)" @click.stop="$emit('feedback', task.id)">➤ 上报</button>
    </footer>
  </article>
</template>
<script setup>
import { computed } from 'vue'
import { STATUS_LABEL } from './legacyAdapter.js'
const props = defineProps({ task: { type: Object, required: true }, selected: Boolean, archived: Boolean })
defineEmits(['select', 'push', 'feedback', 'preview-photo'])
const statusLabel = computed(() => STATUS_LABEL[props.task.status] ?? '待核验')
</script>
<style scoped>
.dr-task-card{position:relative;border:1px solid #e3e9f2;border-radius:12px;background:#fff;min-height:293px;padding:17px 16px 0;display:flex;flex-direction:column;overflow:hidden;transition:box-shadow .15s,border-color .15s}
.dr-task-card:hover,.dr-task-selected{box-shadow:0 4px 18px #3561fa12;border-color:#afcaff}
.dr-task-ribbon{position:absolute;right:0;top:0;border-bottom-left-radius:8px;background:#e7f0ff;color:#3561fa;font-size:12px;padding:8px 15px}
.dr-task-ribbon.dr-status-feedback,.dr-task-ribbon.dr-status-verified,.dr-task-ribbon.dr-status-closed{background:#e8f8ef;color:#159e63}
.dr-task-ribbon.dr-status-processing,.dr-task-ribbon.dr-status-pushed{background:#fff4e3;color:#dc8c14}
.dr-task-head{display:flex;gap:12px;align-items:center;margin-bottom:16px;padding-right:63px}
.dr-task-icon{width:52px;height:52px;border-radius:13px;background:#f2f6fb;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.dr-task-icon img{max-width:37px;max-height:37px;object-fit:contain}
.dr-task-title-group{min-width:0}
.dr-task-title-group h3{font-size:16px;line-height:1.3;margin:0 0 5px;color:#172a45;font-weight:700}
.dr-task-subline{border:1px solid #8aaaff;color:#3561fa;padding:2px 7px;border-radius:20px;font-size:12px;white-space:nowrap}
.dr-no-report{font-size:13px;color:#58677d;margin:0 0 13px}
.dr-task-reporter{display:flex;flex-direction:column;gap:5px;margin-bottom:12px;font-size:12px;color:#697589;min-height:21px}
.dr-task-description{flex:1;border-radius:10px;background:#f5f7fa;color:#66768c;line-height:1.65;padding:12px;font-size:12px;overflow-y:auto;max-height:110px;min-height:90px;white-space:pre-wrap}
.dr-task-feedback{display:flex;align-items:center;gap:10px;margin-top:10px;font-size:12px;color:#66768c}
.dr-task-photos{display:flex;gap:6px}.dr-task-photos button{height:34px;min-width:46px;border:1px solid #dce6f4;background:#f4f8fe;border-radius:4px;cursor:pointer;color:#3561fa}.dr-task-photos img{height:32px;width:45px;object-fit:cover}
.dr-task-actions{display:flex;align-items:center;justify-content:space-around;border-top:1px solid #e8edf5;margin-top:15px;height:44px}
.dr-task-actions button{flex:1;background:transparent;border:0;color:#3263f5;font-size:13px;cursor:pointer}.dr-task-actions button+button{border-left:1px solid #dfe6f2}
.dr-task-actions button:disabled{color:#aeb9c9;cursor:not-allowed}
</style>
