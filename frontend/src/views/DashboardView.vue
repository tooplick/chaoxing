<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, CaretRight, SwitchButton } from '@element-plus/icons-vue'
import { api } from '../api'
import type { Account } from '../types'
import { useAccounts } from '../composables/useAccounts'
import AccountTable from '../components/AccountTable.vue'
import AccountEditDrawer from '../components/AccountEditDrawer.vue'
import StartTaskDialog from '../components/StartTaskDialog.vue'
import LogDrawer from '../components/LogDrawer.vue'
import FaceQrDialog from '../components/FaceQrDialog.vue'

const { accounts, refreshAccounts, statusOf } = useAccounts()

const editVisible = ref(false)
const editingAccount = ref<Account | null>(null)
const startVisible = ref(false)
const startAccount = ref<Account | null>(null)
const logVisible = ref(false)
const logAccountId = ref('')
const faceVisible = ref(false)
const faceAccount = ref<Account | null>(null)
const faceCourseId = ref<string | undefined>(undefined)
const faceJob = ref<string | undefined>(undefined)
const batchBusy = ref(false)

onMounted(refreshAccounts)

function openCreate() {
  editingAccount.value = null
  editVisible.value = true
}

function openEdit(account: Account) {
  editingAccount.value = account
  editVisible.value = true
}

function openStart(account: Account) {
  startAccount.value = account
  startVisible.value = true
}

function openLogs(account: Account) {
  logAccountId.value = account.id
  logVisible.value = true
}

function openFace(account: Account, courseId?: string) {
  faceAccount.value = account
  faceCourseId.value = courseId
  // 被 403 拦截过时带上任务点, 人脸二维码走快路径直接定位
  const st = statusOf(account.id)
  faceJob.value = st.blocked_job ? `${st.blocked_job.jobid}:${st.blocked_job.objectid}` : undefined
  faceVisible.value = true
}

/** 从刷课对话框的预警横幅直接发起人脸采集: 关闭选课框再开扫码框(带上当前选中的课程) */
function onFaceFromDialog(account: Account, courseId?: string) {
  startVisible.value = false
  openFace(account, courseId)
}

async function stopTask(account: Account) {
  try {
    await api.stopTask(account.id)
    ElMessage.success('已请求停止, 当前章节处理完成后生效')
  } catch (err: any) {
    ElMessage.error(err.message ?? '停止失败')
  }
}

const restartingIds = ref<Set<string>>(new Set())

async function restartTask(account: Account) {
  if (restartingIds.value.has(account.id)) return
  restartingIds.value.add(account.id)
  const loadingMsg = ElMessage({
    message: `正在重启「${account.label}」: 停止当前任务后按上次配置重新启动...`,
    type: 'info',
    duration: 0,
  })
  try {
    await api.restartTask(account.id)
    loadingMsg.close()
    ElMessage.success(`「${account.label}」已重启`)
    refreshAccounts()
  } catch (err: any) {
    loadingMsg.close()
    ElMessage.error(err.message ?? '重启失败')
  } finally {
    restartingIds.value.delete(account.id)
  }
}

async function removeAccount(account: Account) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${account.label}」吗? 其 cookies 与运行记录将一并删除。`,
      '删除账号',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api.deleteAccount(account.id)
    ElMessage.success('已删除')
    refreshAccounts()
  } catch (err: any) {
    ElMessage.error(err.message ?? '删除失败')
  }
}

/** 全部启动: 对已记忆课程选择的空闲账号, 用其默认参数逐个启动 */
async function startAll() {
  const targets = accounts.value.filter(
    (a) => a.course_ids?.length && !['starting', 'running'].includes(statusOf(a.id).state),
  )
  if (!targets.length) {
    ElMessage.warning('没有可启动的账号(需先为账号选择过课程)')
    return
  }
  batchBusy.value = true
  let ok = 0
  const failures: string[] = []
  for (const account of targets) {
    try {
      await api.startTask(account.id, { course_ids: account.course_ids, params: account.params })
      ok++
    } catch (err: any) {
      failures.push(`${account.label}: ${err.message}`)
    }
  }
  batchBusy.value = false
  if (ok) ElMessage.success(`已启动 ${ok} 个账号`)
  if (failures.length) {
    ElMessage.error(`部分账号启动失败: ${failures.join('；')}`.slice(0, 800))
  }
}

async function stopAll() {
  batchBusy.value = true
  try {
    const res = await api.stopAll()
    ElMessage.success(`已请求停止 ${res.stopped} 个账号`)
  } catch (err: any) {
    ElMessage.error(err.message ?? '操作失败')
  } finally {
    batchBusy.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-button type="primary" :icon="Plus" @click="openCreate">添加账号</el-button>
      <el-button type="success" :icon="CaretRight" :loading="batchBusy" @click="startAll">全部启动</el-button>
      <el-button type="danger" plain :icon="SwitchButton" :loading="batchBusy" @click="stopAll">全部停止</el-button>
      <span class="muted" style="margin-left: auto">
        多账号同 IP 并发存在平台风控风险, 建议各账号 jobs 不要设置过高
      </span>
    </div>

    <AccountTable
      :accounts="accounts"
      @start="openStart"
      @stop="stopTask"
      @restart="restartTask"
      @face="openFace"
      @logs="openLogs"
      @edit="openEdit"
      @remove="removeAccount"
    />

    <AccountEditDrawer v-model="editVisible" :account="editingAccount" @saved="refreshAccounts" />
    <StartTaskDialog
      v-model="startVisible"
      :account="startAccount"
      @started="refreshAccounts"
      @face="onFaceFromDialog"
    />
    <LogDrawer v-model="logVisible" :account-id="logAccountId" />
    <FaceQrDialog v-model="faceVisible" :account="faceAccount" :course-id="faceCourseId" :blocked-job="faceJob" @verified="refreshAccounts" />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

@media (max-width: 768px) {
  .toolbar {
    flex-wrap: wrap;
    gap: 8px;
  }
  .toolbar .muted {
    flex-basis: 100%;
    margin-left: 0 !important;
  }
  .toolbar .el-button {
    margin: 0;
  }
}
</style>
