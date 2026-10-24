<template>
  <el-dialog
    v-model="dialogVisible"
    title="模型供应商与模型库"
    width="min(1080px, 96vw)"
    append-to-body
    destroy-on-close
  >
    <div class="provider-manager">
      <aside class="provider-list">
        <el-button class="add-provider" plain @click="createProvider">新增 OpenAI-Compatible 供应商</el-button>
        <button
          v-for="provider in providers"
          :key="provider.provider_id"
          type="button"
          class="provider-item"
          :class="{ active: provider.provider_id === form.provider_id }"
          @click="selectProvider(provider)"
        >
          <span>{{ provider.display_name }}</span>
          <small>{{ provider.api_key_set ? 'Key 已配置' : '需配置 Key' }} · {{ provider.is_enabled ? '启用' : '停用' }}</small>
        </button>
      </aside>

      <section v-if="form.provider_id || isNew" class="provider-form">
        <div class="provider-heading">
          <div>
            <h3>{{ form.display_name || '新供应商' }}</h3>
            <p>OpenAI-Compatible 接口；Key 保存在本地 SQLite 中且当前未加密，请在受控环境配置并妥善管理。</p>
          </div>
          <el-switch v-model="form.is_enabled" active-text="启用" inactive-text="停用" />
        </div>

        <el-form label-position="top" class="provider-fields">
          <el-form-item label="供应商 ID">
            <el-input v-model.trim="form.provider_id" :disabled="!isNew" placeholder="例如 modelscope、siliconflow-custom" />
          </el-form-item>
          <el-form-item label="显示名称">
            <el-input v-model.trim="form.display_name" placeholder="例如 ModelScope" />
          </el-form-item>
          <el-form-item label="Base URL">
            <el-input v-model.trim="form.base_url" placeholder="https://api.example.com/v1" />
          </el-form-item>
          <el-form-item label="Embedding API URL（可选覆盖）">
            <el-input v-model.trim="form.embedding_base_url" placeholder="https://api.example.com/v1/embeddings" />
          </el-form-item>
          <el-form-item label="API Key / Token">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="providerKeySet ? '已配置；留空保持不变' : '粘贴服务商 API Key 或 SDK Token'"
            />
          </el-form-item>
          <el-form-item label="环境变量名（可选）">
            <el-input v-model.trim="form.api_key_env" placeholder="PROVIDER_API_KEY" />
          </el-form-item>
          <el-form-item label="能力">
            <el-checkbox-group v-model="form.capabilities">
              <el-checkbox value="embedding">Embedding</el-checkbox>
              <el-checkbox value="rerank">Reranker</el-checkbox>
              <el-checkbox value="chat">Chat</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item label="模型列表 API（可选）">
            <el-input v-model.trim="form.models_endpoint" placeholder="/models" />
          </el-form-item>
          <el-form-item label="Embedding 模型列表 API（可选）">
            <el-input v-model.trim="form.embedding_models_endpoint" placeholder="/embeddings/models；不支持时手动登记模型" />
          </el-form-item>
          <el-form-item label="Reranker 模型列表 API（可选）">
            <el-input v-model.trim="form.rerank_models_endpoint" placeholder="/rerank/models" />
          </el-form-item>
        </el-form>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="只勾选服务商真实提供的接口能力。模型页面可见或网页登录成功，不代表已开通 Embedding API；自定义服务需实现兼容的 /embeddings 接口。"
        />

        <div class="models-heading">
          <div><b>可选模型</b><span>{{ form.enabled_models.length }} 个已登记</span></div>
          <el-button plain :loading="loadingRemoteModels" @click="fetchRemoteModels">拉取远端模型</el-button>
        </div>
        <el-table :data="form.enabled_models" size="small" max-height="190">
          <el-table-column prop="id" label="模型 ID" min-width="210" show-overflow-tooltip />
          <el-table-column prop="type" label="类型" width="100" />
          <el-table-column prop="dimension" label="维度" width="80" />
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :loading="testingSpec === `${form.provider_id}:${row.id}`" @click="testModel(row)">实测</el-button>
              <el-button link type="danger" @click="removeModel(row.id)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="remoteModels.length" class="remote-models">
          <div class="models-heading"><div><b>远端返回</b><span>{{ remoteModels.length }} 个</span></div></div>
          <div v-for="model in remoteModels" :key="`${model.type}:${model.id}`" class="remote-model-row">
            <span>{{ model.id }} <small>{{ model.type }}<template v-if="model.dimension"> · {{ model.dimension }} 维</template></small></span>
            <el-button link type="primary" @click="addModel(model)">加入模型库</el-button>
          </div>
        </div>

        <div class="add-model-row">
          <el-input v-model.trim="draftModel.id" placeholder="手动输入模型 ID，例如 Qwen/Qwen3-Embedding-0.6B" />
          <el-select v-model="draftModel.type" class="model-type-select">
            <el-option label="Embedding" value="embedding" />
            <el-option label="Reranker" value="rerank" />
            <el-option label="Chat" value="chat" />
          </el-select>
          <el-input-number v-if="draftModel.type === 'embedding'" v-model="draftModel.dimension" :min="1" :controls="false" placeholder="维度" />
          <el-button @click="addDraftModel">添加模型</el-button>
        </div>
        <p class="provider-note">保存后模型会出现在知识库的模型选择器中。Embedding 连通性测试会真实请求模型并校验返回向量；未配置 Token 时不会显示为已连通。</p>
      </section>

      <div v-else class="provider-empty">选择供应商进行配置，或新增一个 OpenAI-Compatible 供应商。</div>
    </div>

    <template #footer>
      <el-button @click="dialogVisible = false">关闭</el-button>
      <el-button v-if="form.provider_id || isNew" type="primary" :loading="saving" @click="handleSaveProvider">保存供应商</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getModelProviders, getProviderRemoteModels, saveModelProvider, testProviderModel } from '@/api/geoAiStudio.js'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue', 'saved'])
const dialogVisible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const providers = ref([])
const form = ref(emptyProvider())
const isNew = ref(false)
const providerKeySet = ref(false)
const saving = ref(false)
const loadingRemoteModels = ref(false)
const remoteModels = ref([])
const testingSpec = ref('')
const draftModel = ref({ id: '', type: 'embedding', dimension: null })

function emptyProvider() {
  return {
    provider_id: '', display_name: '', provider_type: 'openai', default_protocol: 'openai',
    base_url: '', embedding_base_url: '', rerank_base_url: '',
    models_endpoint: '/models', embedding_models_endpoint: '/embeddings/models', rerank_models_endpoint: '/rerank/models',
    api_key_env: '', api_key: '', capabilities: ['embedding'], is_enabled: true,
    enabled_models: [], headers_json: {}, extra_json: {},
  }
}

function selectProvider(provider) {
  form.value = { ...emptyProvider(), ...provider, api_key: '', capabilities: [...(provider.capabilities || [])], enabled_models: (provider.enabled_models || []).map((model) => ({ ...model })) }
  isNew.value = false
  providerKeySet.value = Boolean(provider.api_key_set)
  remoteModels.value = []
}

function createProvider() {
  form.value = emptyProvider()
  form.value.display_name = '新供应商'
  isNew.value = true
  providerKeySet.value = false
  remoteModels.value = []
}

async function loadProviders() {
  try {
    const response = await getModelProviders()
    providers.value = response?.data || []
    const preferred = providers.value.find((provider) => provider.provider_id === 'modelscope') || providers.value[0]
    if (preferred) selectProvider(preferred)
    else createProvider()
  } catch (error) {
    providers.value = []
    createProvider()
    ElMessage.error(error.message || '读取模型供应商失败')
  }
}

async function saveProvider(showMessage = true) {
  if (!form.value.provider_id.trim() || !form.value.display_name.trim() || !form.value.base_url.trim()) {
    throw new Error('请填写供应商 ID、显示名称和 Base URL')
  }
  if (!form.value.capabilities.length) throw new Error('至少选择一项模型能力')
  const payload = {
    ...form.value,
    provider_type: 'openai',
    enabled_models: form.value.enabled_models.map((model) => ({ ...model })),
  }
  const saved = await saveModelProvider(payload, isNew.value ? '' : form.value.provider_id)
  const provider = saved?.data
  if (!provider) throw new Error('供应商保存后未返回配置')
  providers.value = [provider, ...providers.value.filter((item) => item.provider_id !== provider.provider_id)]
  selectProvider(provider)
  emit('saved')
  if (showMessage) ElMessage.success('供应商配置已保存')
  return provider
}

async function handleSaveProvider() {
  saving.value = true
  try {
    await saveProvider()
  } catch (error) {
    ElMessage.error(error.message || '保存供应商失败')
  } finally {
    saving.value = false
  }
}

async function fetchRemoteModels() {
  loadingRemoteModels.value = true
  try {
    await saveProvider(false)
    const response = await getProviderRemoteModels(form.value.provider_id)
    remoteModels.value = response?.data || []
    if (!remoteModels.value.length) ElMessage.info('服务未返回模型列表；可手动登记模型 ID')
  } catch (error) {
    ElMessage.error(error.message || '拉取远端模型失败')
  } finally {
    loadingRemoteModels.value = false
  }
}

function addModel(model) {
  if (form.value.enabled_models.some((item) => item.id === model.id)) {
    ElMessage.info('该模型已登记')
    return
  }
  if (!form.value.capabilities.includes(model.type)) form.value.capabilities.push(model.type)
  form.value.enabled_models.push({
    id: model.id,
    display_name: model.display_name || model.id,
    type: model.type,
    source: 'remote',
    ...(model.dimension ? { dimension: Number(model.dimension) } : {}),
    ...(model.batch_size ? { batch_size: Number(model.batch_size) } : {}),
    enabled: true,
  })
}

function addDraftModel() {
  const id = draftModel.value.id.trim()
  if (!id) return ElMessage.warning('请输入模型 ID')
  if (form.value.enabled_models.some((item) => item.id === id)) return ElMessage.warning('该模型已登记')
  if (!form.value.capabilities.includes(draftModel.value.type)) form.value.capabilities.push(draftModel.value.type)
  form.value.enabled_models.push({
    id,
    display_name: id,
    type: draftModel.value.type,
    source: 'manual',
    ...(draftModel.value.type === 'embedding' && draftModel.value.dimension ? { dimension: Number(draftModel.value.dimension) } : {}),
    enabled: true,
  })
  draftModel.value = { id: '', type: 'embedding', dimension: null }
}

function removeModel(modelId) {
  form.value.enabled_models = form.value.enabled_models.filter((model) => model.id !== modelId)
}

async function testModel(model) {
  const spec = `${form.value.provider_id}:${model.id}`
  testingSpec.value = spec
  try {
    await saveProvider(false)
    const result = await testProviderModel(spec)
    if (result.status !== 'available') throw new Error(result.message || '模型连通性测试失败')
    ElMessage.success(`${model.id} 实测通过 · ${result.latency_ms} ms${result.message ? ` · ${result.message}` : ''}`)
  } catch (error) {
    ElMessage.error(error.message || '模型连通性测试失败')
  } finally {
    testingSpec.value = ''
  }
}

watch(() => props.modelValue, (visible) => {
  if (visible) loadProviders()
})
</script>

<style scoped>
.provider-manager { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 18px; min-height: 530px; }
.provider-list { display: flex; flex-direction: column; gap: 8px; border-right: 1px solid var(--el-border-color-lighter); padding-right: 14px; overflow-y: auto; max-height: 68vh; }
.add-provider { width: 100%; margin-bottom: 4px; white-space: normal; }
.provider-item { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 10px 12px; border: 1px solid transparent; border-radius: 8px; background: transparent; text-align: left; cursor: pointer; color: var(--el-text-color-primary); }
.provider-item:hover, .provider-item.active { background: var(--el-fill-color-light); border-color: var(--el-color-primary-light-7); }
.provider-item small { color: var(--el-text-color-secondary); }
.provider-form { min-width: 0; max-height: 68vh; overflow: auto; padding-right: 4px; }
.provider-heading, .models-heading, .remote-model-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.provider-heading { margin-bottom: 14px; }
.provider-heading h3 { margin: 0 0 4px; font-size: 16px; }
.provider-heading p, .provider-note { margin: 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
.provider-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.provider-fields :deep(.el-form-item) { margin-bottom: 10px; }
.models-heading { margin: 8px 0; }
.models-heading div { display: flex; align-items: baseline; gap: 10px; }
.models-heading span { color: var(--el-text-color-secondary); font-size: 12px; }
.remote-models { margin-top: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 8px 12px; max-height: 160px; overflow: auto; }
.remote-model-row { min-height: 34px; border-top: 1px solid var(--el-border-color-lighter); font-size: 13px; }
.remote-model-row small { margin-left: 8px; color: var(--el-text-color-secondary); }
.add-model-row { display: grid; grid-template-columns: minmax(210px, 1fr) 115px 100px auto; gap: 8px; margin: 12px 0; }
.model-type-select { width: 115px; }
.provider-note { margin-top: 8px; }
.provider-empty { display: grid; place-items: center; min-height: 400px; color: var(--el-text-color-secondary); }
@media (max-width: 760px) {
  .provider-manager { grid-template-columns: 1fr; }
  .provider-list { max-height: 150px; border-right: 0; border-bottom: 1px solid var(--el-border-color-lighter); padding: 0 0 10px; }
  .provider-fields { grid-template-columns: 1fr; }
  .add-model-row { grid-template-columns: 1fr; }
  .model-type-select { width: 100%; }
}
</style>
