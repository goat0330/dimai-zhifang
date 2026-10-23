<template>
  <div class="provider-model-select">
    <el-select
      :model-value="modelValue"
      filterable
      allow-create
      default-first-option
      clearable
      :disabled="disabled"
      :loading="loading"
      :placeholder="placeholder || `选择 ${modelTypeLabel}，或手动输入模型 ID`"
      @update:model-value="$emit('update:modelValue', $event || '')"
    >
      <el-option-group v-for="provider in providers" :key="provider.id" :label="provider.name">
        <el-option
          v-for="model in provider.models"
          :key="model.spec"
          :value="model.spec"
          :label="model.display_name"
        >
          <span>{{ model.display_name }}</span>
          <small v-if="model.dimension" class="model-dimension">{{ model.dimension }} 维</small>
        </el-option>
      </el-option-group>
    </el-select>
    <small v-if="!providers.length && !loading" class="model-hint">
      暂无已登记模型；可先管理供应商，或手动输入模型 ID 并填写 Base URL 与 API Key。
    </small>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getProviderModels } from '@/api/geoAiStudio.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  refreshKey: { type: Number, default: 0 },
  modelType: { type: String, default: 'embedding' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
defineEmits(['update:modelValue'])

const providers = ref([])
const loading = ref(false)
const modelTypeLabel = computed(() => ({ embedding: 'Embedding 模型', rerank: 'Reranker 模型', chat: 'Chat 模型' }[props.modelType] || '模型'))

async function loadModels() {
  loading.value = true
  try {
    const result = await getProviderModels(props.modelType)
    providers.value = Object.entries(result?.data || {}).map(([id, provider]) => ({
      id,
      name: provider.provider_display_name || id,
      models: provider.models || [],
    }))
  } catch {
    providers.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadModels)
watch(() => [props.refreshKey, props.modelType], loadModels)
</script>

<style scoped>
.provider-model-select { width: 100%; }
.provider-model-select :deep(.el-select) { width: 100%; }
.model-dimension { float: right; color: var(--el-text-color-secondary); margin-left: 12px; }
.model-hint { display: block; margin-top: 6px; color: var(--el-text-color-secondary); line-height: 1.5; }
</style>
