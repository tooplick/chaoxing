<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElNotification } from 'element-plus'
import { api } from '../api'
import { useIsMobile } from '../composables/useIsMobile'
import type { TikuConfig } from '../types'

const { isMobile } = useIsMobile()

const props = defineProps<{ tiku: TikuConfig }>()
const emit = defineEmits<{ (e: 'update:tiku', value: TikuConfig): void }>()

const fetchingModels = ref(false)
const modelOptions = ref<string[]>([])

/** 用当前表单值(未保存也可)向端点拉取可用模型列表 */
async function fetchModels() {
  fetchingModels.value = true
  try {
    const res = await api.fetchModels(props.tiku)
    if (res.ok === false) throw new Error(res.msg || '获取模型失败')
    modelOptions.value = res.models ?? []
    ElNotification({
      title: '模型列表已更新',
      message: `获取到 ${modelOptions.value.length} 个可用模型，可在「模型」下拉中选择`,
      type: 'success',
      duration: 4000,
    })
  } catch (err: any) {
    ElNotification({
      title: '获取模型失败',
      message: err.message ?? '获取模型失败',
      type: 'error',
      duration: 8000,
      showClose: true,
    })
  } finally {
    fetchingModels.value = false
  }
}

const PROVIDER_OPTIONS = [
  { value: 'TikuYanxi', label: '言溪题库' },
  { value: 'TikuLike', label: 'LIKE 知识库' },
  { value: 'TikuAdapter', label: 'TikuAdapter' },
  { value: 'AI', label: 'AI (OpenAI 兼容)' },
  { value: 'SiliconFlow', label: '硅基流动 SiliconFlow' },
  { value: 'TikuGo', label: 'GO题/网课小工具' },
  { value: 'TikuManual', label: '手动输入 (Web 不支持)' },
]

const chain = computed<string[]>({
  get: () => String(props.tiku.provider ?? '').split(',').map((s) => s.trim()).filter(Boolean),
  set: (list) => update('provider', list.join(',')),
})

function has(...names: string[]) {
  return names.some((n) => chain.value.includes(n))
}

function update(key: string, value: string | number | boolean) {
  emit('update:tiku', { ...props.tiku, [key]: value })
}

function str(key: string, fallback = ''): string {
  const v = props.tiku[key]
  return v === undefined || v === null ? fallback : String(v)
}

function num(key: string, fallback: number): number {
  const v = Number(props.tiku[key])
  return Number.isFinite(v) && props.tiku[key] !== undefined && props.tiku[key] !== '' ? v : fallback
}

function bool(key: string): boolean {
  const v = props.tiku[key]
  return typeof v === 'boolean' ? v : String(v).toLowerCase() === 'true'
}
</script>

<template>
  <el-form
    :label-position="isMobile ? 'top' : 'left'"
    :label-width="isMobile ? '' : '150px'"
    @submit.prevent
  >
    <el-form-item label="题库链 (按序回退)">
      <el-select v-model="chain" multiple placeholder="选择题库, 多个按顺序回退" style="width: 100%">
        <el-option v-for="p in PROVIDER_OPTIONS" :key="p.value" :value="p.value" :label="p.label" />
      </el-select>
      <div class="muted" style="width: 100%">
        手动输入模式(TikuManual)在 Web 端不可用, 启动任务时会被拒绝
      </div>
    </el-form-item>

    <template v-if="chain.length">
      <el-form-item label="提交答题">
        <el-switch :model-value="bool('submit')" @update:model-value="(v: any) => update('submit', !!v)" />
        <span class="muted" style="margin-left: 10px">
          开启后达到覆盖率即提交; 关闭则只保存答案不提交
        </span>
      </el-form-item>
      <el-form-item label="最低题库覆盖率">
        <el-input-number
          :model-value="num('cover_rate', 0.9)"
          :min="0.3"
          :max="1"
          :step="0.05"
          @update:model-value="(v: any) => update('cover_rate', Number(v))"
        />
      </el-form-item>
      <el-form-item label="搜题间隔 (秒)">
        <el-input-number
          :model-value="num('delay', 1)"
          :min="0"
          :step="0.5"
          @update:model-value="(v: any) => update('delay', Number(v))"
        />
      </el-form-item>
    </template>

    <!-- 言溪 / LIKE -->
    <template v-if="has('TikuYanxi', 'TikuLike')">
      <el-divider content-position="left">言溪 / LIKE 题库</el-divider>
      <el-form-item label="Token(s)">
        <el-input
          :model-value="str('tokens').split(',').filter(Boolean).join('\n')"
          type="textarea"
          :rows="2"
          placeholder="多个 token 每行一个, 生成配置时合并为逗号分隔"
          @update:model-value="(v: string) => update('tokens', v.split(/\r?\n/).map(s => s.trim()).filter(Boolean).join(','))"
        />
      </el-form-item>
      <template v-if="has('TikuLike')">
        <el-form-item label="LIKE 模型">
          <el-input :model-value="str('likeapi_model', 'glm-4.5-air')" placeholder="glm-4.5-air" @update:model-value="(v: string) => update('likeapi_model', v)" />
        </el-form-item>
        <el-form-item label="联网搜索">
          <el-switch :model-value="bool('likeapi_search')" @update:model-value="(v: any) => update('likeapi_search', !!v)" />
        </el-form-item>
        <el-form-item label="视觉能力">
          <el-switch :model-value="bool('likeapi_vision')" @update:model-value="(v: any) => update('likeapi_vision', !!v)" />
        </el-form-item>
        <el-form-item label="自动重试">
          <el-switch :model-value="bool('likeapi_retry')" @update:model-value="(v: any) => update('likeapi_retry', !!v)" />
          <el-input-number
            v-if="bool('likeapi_retry')"
            :model-value="num('likeapi_retry_times', 3)"
            :min="1"
            :max="10"
            style="margin-left: 12px"
            @update:model-value="(v: any) => update('likeapi_retry_times', Number(v))"
          />
        </el-form-item>
      </template>
    </template>

    <!-- TikuAdapter -->
    <template v-if="has('TikuAdapter')">
      <el-divider content-position="left">TikuAdapter</el-divider>
      <el-form-item label="服务地址 URL">
        <el-input :model-value="str('url')" placeholder="https://your-tikuAdapter/api" @update:model-value="(v: string) => update('url', v)" />
      </el-form-item>
    </template>

    <!-- GO题 -->
    <template v-if="has('TikuGo')">
      <el-divider content-position="left">GO题 (网课小工具)</el-divider>
      <el-form-item label="解除限流 Token">
        <el-input :model-value="str('go_authorization')" placeholder="可选" @update:model-value="(v: string) => update('go_authorization', v)" />
      </el-form-item>
      <el-form-item label="最小间隔 (秒)">
        <el-input-number :model-value="num('go_min_interval', 1)" :min="0.5" :step="0.5" @update:model-value="(v: any) => update('go_min_interval', Number(v))" />
      </el-form-item>
      <el-form-item label="重试次数">
        <el-input-number :model-value="num('go_retry_times', 3)" :min="1" :max="10" @update:model-value="(v: any) => update('go_retry_times', Number(v))" />
      </el-form-item>
      <el-form-item label="重试退避倍数">
        <el-input-number :model-value="num('go_retry_backoff', 1.2)" :min="1" :max="5" :step="0.1" @update:model-value="(v: any) => update('go_retry_backoff', Number(v))" />
      </el-form-item>
    </template>

    <!-- AI -->
    <template v-if="has('AI')">
      <el-divider content-position="left">AI 大模型 (OpenAI 兼容)</el-divider>
      <el-form-item label="API Endpoint">
        <el-input :model-value="str('endpoint')" placeholder="https://example.com/v1" @update:model-value="(v: string) => update('endpoint', v)" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input :model-value="str('key')" type="password" show-password @update:model-value="(v: string) => update('key', v)" />
      </el-form-item>
      <el-form-item label="模型">
        <div class="model-row">
          <el-select
            :model-value="str('model')"
            filterable
            allow-create
            default-first-option
            placeholder="点击右侧「获取模型」, 或直接输入模型名"
            class="model-select"
            @update:model-value="(v: string) => update('model', v)"
          >
            <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
          </el-select>
          <el-button :loading="fetchingModels" @click="fetchModels">获取模型</el-button>
        </div>
      </el-form-item>
      <el-form-item label="请求间隔 (秒)">
        <el-input-number :model-value="num('min_interval_seconds', 3)" :min="0" @update:model-value="(v: any) => update('min_interval_seconds', Number(v))" />
      </el-form-item>
      <el-form-item label="HTTP 代理">
        <el-input :model-value="str('http_proxy')" placeholder="http://examples.com (可选)" @update:model-value="(v: string) => update('http_proxy', v)" />
      </el-form-item>
    </template>

    <!-- SiliconFlow -->
    <template v-if="has('SiliconFlow')">
      <el-divider content-position="left">硅基流动 SiliconFlow</el-divider>
      <el-form-item label="API Key">
        <el-input :model-value="str('siliconflow_key')" type="password" show-password @update:model-value="(v: string) => update('siliconflow_key', v)" />
      </el-form-item>
      <el-form-item label="模型">
        <div class="model-row">
          <el-select
            :model-value="str('siliconflow_model', 'deepseek-ai/DeepSeek-R1')"
            filterable
            allow-create
            default-first-option
            placeholder="点击右侧「获取模型」, 或直接输入模型名"
            class="model-select"
            @update:model-value="(v: string) => update('siliconflow_model', v)"
          >
            <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
          </el-select>
          <el-button :loading="fetchingModels" @click="fetchModels">获取模型</el-button>
        </div>
      </el-form-item>
      <el-form-item label="自定义端点">
        <el-input :model-value="str('siliconflow_endpoint')" placeholder="默认官方端点, 一般无需修改" @update:model-value="(v: string) => update('siliconflow_endpoint', v)" />
      </el-form-item>
    </template>

    <el-collapse v-if="chain.length" style="margin-top: 8px">
      <el-collapse-item title="高级: 判断题选项词表" name="adv">
        <el-form-item label="判为「正确」的词">
          <el-input :model-value="str('true_list', '正确,对,√,是')" @update:model-value="(v: string) => update('true_list', v)" />
        </el-form-item>
        <el-form-item label="判为「错误」的词">
          <el-input :model-value="str('false_list', '错误,错,×,否,不对,不正确')" @update:model-value="(v: string) => update('false_list', v)" />
        </el-form-item>
      </el-collapse-item>
    </el-collapse>
  </el-form>
</template>

<style scoped>
.model-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.model-select {
  flex: 1;
}
</style>
