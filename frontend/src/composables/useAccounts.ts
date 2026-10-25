import { computed, ref } from 'vue'
import { ElNotification } from 'element-plus'
import { api } from '../api'
import type { Account, AccountStatus } from '../types'

/** 模块级共享状态(单页面板规模, 不引入 pinia) */
const accounts = ref<Account[]>([])
const statuses = ref<AccountStatus[]>([])
let timer: ReturnType<typeof setInterval> | null = null
/** 上一轮已提醒过的账号, needs_attention 从无到有才弹通知 */
const notified = new Set<string>()
/** 判别中未弹通知的账号及其等待轮数(判别超时后弹通用文案) */
const diagnosingCounts = new Map<string, number>()
/** 已按判别结果补发过最终通知的账号 */
const reasonNotified = new Set<string>()

export function useAccounts() {
  async function refreshAccounts() {
    const data = await api.listAccounts()
    accounts.value = data.accounts ?? []
  }

  function checkNeedsAttention(next: AccountStatus[]) {
    for (const item of next) {
      if (item.needs_attention && !notified.has(item.id)) {
        // 等待后端判别结果(人脸/冷却); 等待超过 ~20 轮(40 秒)回退通用文案
        const waits = (diagnosingCounts.get(item.id) ?? 0) + 1
        diagnosingCounts.set(item.id, waits)
        if (item.blocked_reason == null && waits < 20) continue
        notified.add(item.id)
        diagnosingCounts.delete(item.id)
        const reason = item.blocked_reason
        const message =
          reason === 'face'
            ? '检测到人脸采集要求：点账号行的「人脸」按钮获取二维码，用学习通App扫码完成验证后即可重启。'
            : reason === 'cooldown'
              ? '风控冷却中：建议等待 30-60 分钟再点「重启」，期间不要反复启动以免加深风控。'
              : '任务因连续 403 拦截已自动停止。可点「人脸」按钮检测是否需要人脸采集，或等待 30-60 分钟后再重启。'
        ElNotification({
          title: `「${item.label}」需要人工处理`,
          message,
          type: 'error',
          duration: 0,
          showClose: true,
        })
      } else if (item.needs_attention && item.blocked_reason && !reasonNotified.has(item.id)) {
        // 判别结果晚于首条通知到达时, 补发明确的最终通知
        reasonNotified.add(item.id)
        const isFace = item.blocked_reason === 'face'
        ElNotification({
          title: isFace ? `「${item.label}」需要人脸采集` : `「${item.label}」风控冷却中`,
          message: isFace
            ? '已确认是人脸抓拍要求：点账号行的「人脸」按钮获取二维码，用学习通App扫码完成验证后即可重启。'
            : '已确认无需人脸采集，属风控冷却：建议等待 30-60 分钟再点「重启」。',
          type: isFace ? 'error' : 'warning',
          duration: 0,
          showClose: true,
        })
      } else if (!item.needs_attention) {
        notified.delete(item.id)
        diagnosingCounts.delete(item.id)
        reasonNotified.delete(item.id)
      }
    }
  }

  async function refreshStatus() {
    try {
      const data = await api.status()
      statuses.value = data.accounts ?? []
      checkNeedsAttention(statuses.value)
    } catch {
      // 轮询失败不打断页面, 下个周期重试
    }
  }

  function startPolling() {
    if (timer === null) {
      refreshStatus()
      timer = setInterval(refreshStatus, 2000)
    }
  }

  function stopPolling() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  const statusMap = computed(() => {
    const map: Record<string, AccountStatus> = {}
    for (const item of statuses.value) map[item.id] = item
    return map
  })

  function statusOf(id: string): AccountStatus {
    return (
      statusMap.value[id] ?? { id, label: '', username: '', state: 'idle' }
    )
  }

  return { accounts, statuses, statusMap, statusOf, refreshAccounts, refreshStatus, startPolling, stopPolling }
}
