<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '../api'
import { useIsMobile } from '../composables/useIsMobile'

const { isMobile } = useIsMobile()
import type { Account } from '../types'

const props = defineProps<{ modelValue: boolean; account: Account | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'verified'): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const qrImage = ref('')
const chapter = ref('')
const loading = ref(false)
const error = ref('')
const done = ref(false)
const checking = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function loadQr() {
  if (!props.account) return
  loading.value = true
  error.value = ''
  done.value = false
  try {
    const res = await api.faceQr(props.account.id)
    if (!res.ok || !res.qr_base64) throw new Error(res.msg || '获取二维码失败')
    qrImage.value = `data:image/png;base64,${res.qr_base64}`
    chapter.value = res.chapter ?? ''
    startPolling()
  } catch (err: any) {
    error.value = err.message ?? '获取二维码失败'
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (checking.value || !props.account) return
    checking.value = true
    try {
      const res = await api.faceStatus(props.account.id)
      if (res.done) {
        done.value = true
        stopPolling()
        ElMessage.success('人脸验证已完成, 现在可以重启任务了')
        emit('verified')
      }
    } catch {
      // 轮询失败忽略, 下个周期重试
    } finally {
      checking.value = false
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(visible, (open) => {
  if (open && props.account) loadQr()
  else stopPolling()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <el-dialog v-model="visible" title="人脸信息采集" :width="isMobile ? '92%' : '420px'" @submit.prevent>
    <div v-loading="loading" element-loading-text="正在定位待验证的章节(约需数秒)..." :style="{ minHeight: '280px' }">
      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" style="margin-bottom: 12px">
        <el-button size="small" type="primary" @click="loadQr">重试</el-button>
      </el-alert>

      <template v-if="qrImage && !done">
        <p class="muted" style="text-align: center; margin: 0 0 10px">
          用登录了「{{ account?.label }}」的学习通 App 扫描二维码<br />
          在 App 内按提示完成人脸采集{{ chapter ? `（触发章节：${chapter}）` : '' }}
        </p>
        <div class="qr-wrap">
          <img :src="qrImage" alt="人脸采集二维码" />
        </div>
        <p class="muted" style="text-align: center">
          页面每 3 秒自动检测验证状态，完成后会自动提示
          <el-button size="small" :icon="Refresh" text type="primary" @click="loadQr">刷新二维码</el-button>
        </p>
      </template>

      <el-result v-if="done" icon="success" title="人脸验证完成" sub-title="拦截已解除，关闭本窗口后到列表点「重启」继续刷课" />
    </div>
  </el-dialog>
</template>

<style scoped>
.qr-wrap {
  display: flex;
  justify-content: center;
  padding: 12px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 10px;
}
.qr-wrap img {
  width: 240px;
  height: 240px;
  image-rendering: pixelated;
}
</style>
