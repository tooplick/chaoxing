<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '../api'
import type { Account, AccountParams, Course } from '../types'
import ParamsForm from './ParamsForm.vue'
import { useIsMobile } from '../composables/useIsMobile'
import { useAccounts } from '../composables/useAccounts'

const { isMobile } = useIsMobile()
const { statusOf } = useAccounts()

/** 账号当前是否在运行(运行中可调整并保存, 但不能重复启动) */
const isRunning = computed(() =>
  props.account ? ['starting', 'running'].includes(statusOf(props.account.id).state) : false,
)

const props = defineProps<{ modelValue: boolean; account: Account | null }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'started'): void
  (e: 'face', account: Account): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const courses = ref<Course[]>([])
const loading = ref(false)
const loadError = ref('')
const fetchedAt = ref<number | null>(null)
const tableRef = ref<any>(null)
const selected = ref<Course[]>([])
const params = ref<AccountParams | null>(null)
const saveDefault = ref(true)
const starting = ref(false)
const saving = ref(false)
const faceChecking = ref(false)
const faceCapture = ref<Record<string, boolean | null>>({})
const tikuChecking = ref(false)

const selectedCourseIds = computed(() => selected.value.map((c) => c.courseId))

/** 所选课程中含人脸抓拍的 */
const selectedWithFace = computed(() =>
  selected.value.filter((c) => faceCapture.value[c.courseId] === true),
)

async function checkFaceConfig() {
  if (!props.account || !courses.value.length || faceChecking.value) return
  faceChecking.value = true
  try {
    const res = await api.faceConfig(props.account.id, courses.value.map((c) => c.courseId))
    const map: Record<string, boolean | null> = {}
    for (const item of res.results ?? []) map[item.courseId] = item.face_capture
    faceCapture.value = map
    const faceCount = Object.values(map).filter(Boolean).length
    ElMessage.success(faceCount ? `${faceCount} 门课程配置了人脸抓拍（未完成采集）` : '所有课程均无人脸抓拍要求')
  } catch (err: any) {
    ElMessage.error(err.message ?? '检测失败')
  } finally {
    faceChecking.value = false
  }
}

/** 检查设置页保存的题库配置(大模型真连一次, 其余题库字段校验), 结果以全局通知弹出 */
async function checkTiku() {
  if (tikuChecking.value) return
  tikuChecking.value = true
  try {
    const res = await api.testTiku()
    if (res.ok) {
      ElNotification({
        title: '题库正常',
        message: res.msg || '连接成功，答题功能可用',
        type: 'success',
        duration: 4000,
      })
    } else {
      ElNotification({
        title: '题库异常',
        message: `${res.msg || '测试失败'} — 只影响答题准确率，不影响视频/文档任务`,
        type: 'error',
        duration: 8000,
        showClose: true,
      })
    }
  } catch (err: any) {
    ElNotification({
      title: '题库异常',
      message: `${err.message ?? '检查失败'} — 只影响答题准确率，不影响视频/文档任务`,
      type: 'error',
      duration: 8000,
      showClose: true,
    })
  } finally {
    tikuChecking.value = false
  }
}

/** fetched_at 距今超过 2 分钟视为陈旧数据, 提示可刷新 */
const fetchedAtText = computed(() => {
  if (!fetchedAt.value || !courses.value.length) return ''
  const age = Date.now() / 1000 - fetchedAt.value
  if (age > 120) {
    const d = new Date(fetchedAt.value * 1000)
    return `上次获取 ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  }
  return ''
})

/** 恢复上次选择的课程: 数据层直接赋值(横幅/启动按钮立即正确), 再同步表格勾选 UI */
async function restoreSelection() {
  await nextTick()
  const remembered = new Set(props.account?.course_ids ?? [])
  const initial = courses.value.filter((c) => remembered.has(c.courseId))
  selected.value = initial
  tableRef.value?.clearSelection()
  for (const row of initial) {
    tableRef.value?.toggleRowSelection(row, true)
  }
}

async function loadCourses(refresh = false) {
  if (!props.account) return
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.accountCourses(props.account.id, refresh)
    if (!res.ok) throw new Error(res.msg || '获取课程失败')
    courses.value = res.courses ?? []
    fetchedAt.value = res.fetched_at ?? null
    await restoreSelection()
  } catch (err: any) {
    loadError.value = err.message ?? '获取课程失败'
  } finally {
    loading.value = false
  }
}

function defaultParams(): AccountParams {
  return {
    speed: 1,
    jobs: 4,
    notopen_action: 'retry',
    retry_interval: 1,
    work_redo_enabled: false,
    work_max_retries: 3,
    add_learning_count: false,
    target_count: 100,
  }
}

watch(visible, (open) => {
  if (!open || !props.account) return
  selected.value = []
  params.value = { ...defaultParams(), ...props.account.params }
  loadCourses()
})

function selectAll() {
  for (const row of courses.value) tableRef.value?.toggleRowSelection(row, true)
}

function clearSelection() {
  tableRef.value?.clearSelection()
}

/** 只保存当前课程选择与参数为账号默认, 不启动任务 */
async function saveSelection() {
  if (!props.account) return
  if (!selected.value.length) {
    ElMessage.warning('请先选择课程')
    return
  }
  saving.value = true
  try {
    await api.updateAccount(props.account.id, {
      course_ids: selectedCourseIds.value,
      params: params.value,
    })
    ElMessage.success('已保存课程选择与参数（全部启动也将使用它们）')
  } catch (err: any) {
    ElMessage.error(err.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

async function start() {
  if (!props.account || !params.value) return
  if (!selected.value.length) {
    ElMessage.warning('请至少选择一门课程')
    return
  }
  starting.value = true
  try {
    await api.startTask(props.account.id, {
      course_ids: selectedCourseIds.value,
      chapters_courses: selected.value.map((c) => `${c.courseId}:${c.clazzId}:${c.cpi}`),
      params: params.value,
      save_default: saveDefault.value,
    })
    ElMessage.success('任务已启动')
    visible.value = false
    emit('started')
  } catch (err: any) {
    ElMessage.error({ message: err.message ?? '启动失败', duration: 6000, showClose: true })
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="`刷课 - ${account?.label ?? ''}`" :width="isMobile ? '95%' : '860px'" top="4vh">
      <el-alert
        v-if="isRunning"
        type="info"
        :closable="false"
        style="margin-bottom: 12px"
        title="该账号有任务运行中：可调整课程与参数后点「保存选择」（下次重启生效），或先停止当前任务再启动"
      />

      <div v-loading="loading">
      <div class="section-title">
        <span>选择课程</span>
        <span class="muted" style="margin-left: 10px">已选 {{ selected.length }} / {{ courses.length }} 门</span>
        <span v-if="fetchedAtText" class="muted">{{ fetchedAtText }}</span>
        <el-button size="small" style="margin-left: auto" @click="selectAll">全选</el-button>
        <el-button size="small" @click="clearSelection">清空</el-button>
        <el-button size="small" :loading="faceChecking" @click="checkFaceConfig">检测人脸</el-button>
        <el-button size="small" :loading="tikuChecking" @click="checkTiku">检查题库</el-button>
        <el-button size="small" :icon="Refresh" circle @click="loadCourses(true)" />
      </div>

      <el-alert
        v-if="selectedWithFace.length"
        type="warning"
        :closable="false"
        style="margin-bottom: 12px"
      >
        <template #title>
          所选 {{ selectedWithFace.length }} 门课程要求人脸采集（未完成时视频到抓拍点会被拦）：
          <el-button size="small" type="danger" @click="emit('face', props.account!)">立即采集</el-button>
          完成后抓拍要求即满足
        </template>
      </el-alert>

      <el-alert v-if="loadError" type="error" :title="loadError" show-icon :closable="false" style="margin-bottom: 12px">
        <el-button size="small" type="primary" @click="loadCourses">重试</el-button>
      </el-alert>

        <el-table
          ref="tableRef"
          :data="courses"
          row-key="courseId"
          max-height="320"
          size="small"
          @selection-change="(rows: Course[]) => (selected = rows)"
        >
          <el-table-column type="selection" width="42" />
        <el-table-column prop="title" label="课程名" min-width="180" show-overflow-tooltip />
        <el-table-column label="人脸" width="70">
          <template #default="{ row }">
            <el-tag v-if="faceCapture[row.courseId] === true" type="danger" size="small">需采集</el-tag>
            <el-tag v-else-if="faceCapture[row.courseId] === false" type="success" size="small">无</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="teacher" label="教师" min-width="100" show-overflow-tooltip class-name="hide-mobile" />
        <el-table-column prop="courseId" label="课程ID" width="100" class-name="hide-mobile" />
        <el-table-column prop="clazzId" label="班级ID" width="100" class-name="hide-mobile" />
      </el-table>

      <el-collapse style="margin: 4px 0 8px">
        <el-collapse-item name="params">
          <template #title>
            <span style="font-weight: 600">刷课参数</span>
            <span class="muted" style="margin-left: 8px">倍速 / 并发 / 重做等，默认折叠，点开调整</span>
          </template>
          <el-checkbox v-model="saveDefault" style="margin-bottom: 8px">保存为该账号默认参数</el-checkbox>
          <ParamsForm v-if="params" v-model:params="params" />
        </el-collapse-item>
      </el-collapse>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button :loading="saving" :disabled="!selected.length" @click="saveSelection">保存选择</el-button>
      <el-button type="primary" :loading="starting" :disabled="!selected.length || isRunning" @click="start">
        {{ isRunning ? '运行中不可启动' : '启动刷课' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.section-title {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  font-weight: 600;
}
</style>
