<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { useIsMobile } from '../composables/useIsMobile'

const { isMobile } = useIsMobile()

const props = defineProps<{ modelValue: boolean; accountId: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const MAX_LINES = 3000
const lines = ref<string[]>([])
const autoScroll = ref(true)
const connected = ref(false)
const terminalRef = ref<HTMLElement | null>(null)
let source: EventSource | null = null
let lastSeq = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

const LEVEL_RE = /\b(TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR)\b/

function lineClass(text: string): string {
  if (text.startsWith('[Web]')) return 'log-WEB'
  const match = text.match(LEVEL_RE)
  return match ? `log-${match[1]}` : 'log-INFO'
}

function appendLine(text: string) {
  lines.value.push(text)
  if (lines.value.length > MAX_LINES) {
    lines.value.splice(0, lines.value.length - MAX_LINES)
  }
  if (autoScroll.value) {
    nextTick(() => {
      const el = terminalRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }
}

function connect(after: number) {
  disconnect()
  // 带 last_seq 断线续传, 避免 EventSource 自动重连(固定初始 after=0)造成的全量重放
  source = new EventSource(`/api/accounts/${props.accountId}/logs?after=${after}`)
  source.onopen = () => (connected.value = true)
  source.onmessage = (event) => {
    try {
      appendLine(JSON.parse(event.data))
    } catch {
      appendLine(event.data)
    }
    const seq = Number(event.lastEventId)
    if (Number.isFinite(seq) && seq > 0) lastSeq = seq
  }
  // 服务端回放完毕且运行已结束时推送 end, 主动关闭避免 EventSource 自动重连
  source.addEventListener('end', () => {
    appendLine('[Web] 日志流已结束')
    disconnect()
  })
  source.onerror = () => {
    connected.value = false
    // 主动接管重连: 关闭后延时用 lastSeq 重建连接(抽屉已关闭则不再重连)
    const seq = lastSeq
    source?.close()
    source = null
    if (visible.value) {
      reconnectTimer = setTimeout(() => connect(seq), 3000)
    }
  }
}

function disconnect() {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  source?.close()
  source = null
  connected.value = false
}

watch(visible, (open) => {
  if (open && props.accountId) {
    lastSeq = 0
    lines.value = []
    connect(0)
  } else {
    disconnect()
  }
})
onBeforeUnmount(disconnect)
</script>

<template>
  <el-drawer v-model="visible" title="运行日志" :size="isMobile ? '95%' : '62%'">
    <div class="log-toolbar">
      <el-tag :type="connected ? 'success' : 'info'" size="small">
        {{ connected ? '实时推送中' : '未连接' }}
      </el-tag>
      <el-button size="small" @click="autoScroll = !autoScroll">
        {{ autoScroll ? '暂停滚动' : '继续滚动' }}
      </el-button>
      <el-button size="small" :icon="Delete" @click="lines = []">清空</el-button>
    </div>
    <div ref="terminalRef" class="log-terminal">
      <span v-for="(line, i) in lines" :key="i" class="log-line" :class="lineClass(line)">{{ line }}</span>
      <div v-if="!lines.length" class="muted">等待日志...</div>
    </div>
  </el-drawer>
</template>

<style scoped>
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.log-terminal {
  height: calc(100% - 42px);
}
</style>
