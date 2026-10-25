<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { ElTooltip } from 'element-plus'
import {
  CaretRight, SwitchButton, RefreshRight, Document, EditPen, Delete, Camera, Refresh,
} from '@element-plus/icons-vue'
import type { Account, RunState } from '../types'
import { useAccounts } from '../composables/useAccounts'
import { api } from '../api'

defineProps<{ accounts: Account[] }>()
defineEmits<{
  (e: 'start', account: Account): void
  (e: 'stop', account: Account): void
  (e: 'restart', account: Account): void
  (e: 'face', account: Account): void
  (e: 'logs', account: Account): void
  (e: 'edit', account: Account): void
  (e: 'remove', account: Account): void
}>()

const { statusOf } = useAccounts()

/** 展开状态自管理 */
const expandedIds = ref<Set<string>>(new Set())

function toggleExpand(account: Account, event: Event) {
  const target = event.target as HTMLElement
  if (target.closest('.ops-area')) return
  const next = new Set(expandedIds.value)
  if (next.has(account.id)) next.delete(account.id)
  else next.add(account.id)
  expandedIds.value = next
  if (next.has(account.id)) loadTree(account.id)
}

const stateMeta: Record<RunState, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  idle: { label: '空闲', type: 'info' },
  starting: { label: '启动中', type: 'warning' },
  running: { label: '运行中', type: 'success' },
  finished: { label: '已完成', type: 'success' },
  stopped: { label: '已停止', type: 'warning' },
  error: { label: '出错', type: 'danger' },
}

const avatarColors: Record<RunState, string> = {
  idle: '#909399',
  starting: '#e6a23c',
  running: '#67c23a',
  finished: '#67c23a',
  stopped: '#e6a23c',
  error: '#f56c6c',
}

function percent(st: { completed?: number; total?: number | null }) {
  if (!st.total) return 0
  return Math.round(((st.completed ?? 0) / st.total) * 100)
}

/** 动态行: 运行中→课程·章节·视频; 出错→错误摘要; 其余→课程数 */
function activityText(account: Account, id: string): string {
  const st = statusOf(id)
  if (st.error && st.state === 'error') return st.error
  const parts: string[] = []
  if (st.current_course) parts.push(st.current_course)
  if (st.current_chapter) parts.push(st.current_chapter)
  const playing = st.videos?.find((v) => v.percent < 100)
  if (playing) parts.push(`${playing.name} ${playing.percent}%`)
  if (parts.length) return parts.join(' · ')
  if (account.course_ids?.length) return `已选 ${account.course_ids.length} 门课程`
  return '尚未发起刷课'
}

interface JobNode {
  type: string
  name: string
  done: boolean
}
interface ChapterNode {
  id: string
  title: string
  done: boolean
  jobs?: JobNode[]
}
interface CourseTree {
  courseId: string
  title?: string
  chapters: ChapterNode[]
}

/** 展开行的章节树数据 */
const treeData = ref<Record<string, CourseTree[]>>({})
const treeLoading = ref<Record<string, boolean>>({})
/** 课程分组展开状态: 全部章节完成的课程默认收起 */
const courseOpen = ref<Record<string, boolean>>({})

function initCourseOpen(accountId: string, courses: CourseTree[]) {
  const state: Record<string, boolean> = { ...courseOpen.value }
  for (const course of courses) {
    const key = `${accountId}/${course.courseId}`
    if (key in state) continue // 用户手动切换过的保持
    const allDone = course.chapters.length > 0 && course.chapters.every((c) => c.done)
    state[key] = !allDone
  }
  courseOpen.value = state
}

function toggleCourse(accountId: string, courseId: string) {
  const key = `${accountId}/${courseId}`
  courseOpen.value = { ...courseOpen.value, [key]: !courseOpen.value[key] }
}
/** 全量任务点是否已合并(合并后章节点击为本地展开) */
const jobsLoaded = ref<Record<string, boolean>>({})
const jobsLoading = ref<Record<string, boolean>>({})

/** 保存/还原章节树滚动位置: 刷新重建 DOM 后不跳回顶部 */
function saveScroll(accountId: string): number {
  const el = document.querySelector(`.tree-box[data-account="${accountId}"]`) as HTMLElement | null
  return el?.scrollTop ?? 0
}

function restoreScroll(accountId: string, top: number) {
  nextTick(() => {
    const el = document.querySelector(`.tree-box[data-account="${accountId}"]`) as HTMLElement | null
    if (el) el.scrollTop = top
  })
}

async function loadTree(accountId: string, refresh = false) {
  if (treeLoading.value[accountId]) return
  if (!refresh && treeData.value[accountId]) {
    if (!jobsLoaded.value[accountId]) loadJobs(accountId)
    return
  }
  treeLoading.value = { ...treeLoading.value, [accountId]: true }
  const scrollTop = saveScroll(accountId)
  try {
    const res = await api.chapterTree(accountId, refresh)
    treeData.value = { ...treeData.value, [accountId]: res.courses ?? [] }
    initCourseOpen(accountId, res.courses ?? [])
    restoreScroll(accountId, scrollTop)
    // 手动刷新不触发自动定位, 保持用户当前滚动位置
    if (!refresh) locateCurrentChapter(accountId)
    if (refresh) jobsLoaded.value = { ...jobsLoaded.value, [accountId]: false }
    loadJobs(accountId, refresh)
  } catch {
    treeData.value = { ...treeData.value, [accountId]: [] }
  } finally {
    treeLoading.value = { ...treeLoading.value, [accountId]: false }
  }
}

/** 后台拉取带任务点的全量树并合并, 完成后所有章节本地展开 */
async function loadJobs(accountId: string, refresh = false) {
  if (!refresh && (jobsLoading.value[accountId] || jobsLoaded.value[accountId])) return
  jobsLoading.value = { ...jobsLoading.value, [accountId]: true }
  const scrollTop = saveScroll(accountId)
  try {
    const res = await api.chapterTree(accountId, refresh, true)
    if (res.courses?.length) {
      treeData.value = { ...treeData.value, [accountId]: res.courses }
      initCourseOpen(accountId, res.courses)
      jobsLoaded.value = { ...jobsLoaded.value, [accountId]: true }
      restoreScroll(accountId, scrollTop)
      if (!refresh) locateCurrentChapter(accountId)
    }
  } catch {
    // 全量失败时保留纯树, 章节点击回退单章请求
  } finally {
    jobsLoading.value = { ...jobsLoading.value, [accountId]: false }
  }
}

/** 展开详情渲染后, 把当前正在刷的章节滚动到可视区中央(仅首次加载定位, 刷新不打扰滚动位置) */
const locatedIds = ref<Set<string>>(new Set())

function locateCurrentChapter(accountId: string) {
  if (locatedIds.value.has(accountId)) return
  locatedIds.value.add(accountId)
  nextTick(() => {
    setTimeout(() => {
      document
        .querySelector(`.tree-box[data-account="${accountId}"] .chapter-item.current`)
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }, 120)
  })
}

/** 章节二级展开: 任务点列表 */
const chapterJobs = ref<Record<string, JobNode[]>>({})
const chapterOpen = ref<Record<string, boolean>>({})
const chapterLoading = ref<Record<string, boolean>>({})

async function toggleChapter(accountId: string, courseId: string, chapter: ChapterNode) {
  const key = `${accountId}/${chapter.id}`
  const opening = !chapterOpen.value[key]
  chapterOpen.value = { ...chapterOpen.value, [key]: opening }
  // 全量任务点已合并时直接本地展开
  if (chapter.jobs) return
  if (!opening || chapterJobs.value[key] || chapterLoading.value[key]) return
  chapterLoading.value = { ...chapterLoading.value, [key]: true }
  try {
    const res = await api.chapterJobs(accountId, courseId, chapter.id)
    chapterJobs.value = { ...chapterJobs.value, [key]: res.jobs ?? [] }
  } catch {
    chapterJobs.value = { ...chapterJobs.value, [key]: [] }
  } finally {
    chapterLoading.value = { ...chapterLoading.value, [key]: false }
  }
}

const jobTypeMeta: Record<string, { icon: string; label: string }> = {
  video: { icon: '▶', label: '视频' },
  document: { icon: '▤', label: '文档' },
  workid: { icon: '✎', label: '测验' },
  read: { icon: '📖', label: '阅读' },
  live: { icon: '📡', label: '直播' },
}

/** 该任务点若正在观看, 返回其实时进度 */
function playingVideo(accountId: string, jobName: string) {
  return (statusOf(accountId).videos ?? []).find((v) => v.name === jobName)
}
</script>

<template>
  <div class="account-list">
    <div v-if="!accounts.length" class="empty-tip">还没有账号, 点击上方「添加账号」开始</div>

    <div v-for="account in accounts" :key="account.id" class="account-card" :class="{ expanded: expandedIds.has(account.id) }">
      <!-- 卡片头 -->
      <div class="card-head" @click="toggleExpand(account, $event)">
        <div class="avatar" :style="{ background: avatarColors[statusOf(account.id).state] }">
          {{ (account.label || account.username).slice(0, 1).toUpperCase() }}
        </div>

        <div class="id-block">
          <div class="label-line">{{ account.label || account.username }}</div>
          <div class="phone-line">{{ account.username }}</div>
        </div>

        <div class="status-block">
          <el-tag :type="stateMeta[statusOf(account.id).state].type" effect="light" size="small">
            {{ stateMeta[statusOf(account.id).state].label }}
          </el-tag>
          <div v-if="statusOf(account.id).blocked_reason" class="blocked-line">
            {{ statusOf(account.id).blocked_reason === 'face' ? '需人脸采集' : '风控冷却中' }}
          </div>
        </div>

        <div class="progress-block">
          <div v-if="statusOf(account.id).total" class="progress-row">
            <el-progress
              :percentage="percent(statusOf(account.id))"
              :stroke-width="8"
              :show-text="false"
              :status="statusOf(account.id).state === 'error' ? 'exception' : undefined"
              class="progress-bar"
            />
            <span class="progress-text">
              {{ percent(statusOf(account.id) ) }}% · {{ statusOf(account.id).completed ?? 0 }}/{{ statusOf(account.id).total }}
            </span>
          </div>
          <div v-else class="progress-row">
            <span class="muted">
              {{ (statusOf(account.id).completed ?? 0) || (statusOf(account.id).failed ?? 0) ? `完成 ${statusOf(account.id).completed ?? 0}` : '—' }}
            </span>
          </div>
          <div class="activity-line" :class="{ 'is-error': statusOf(account.id).state === 'error' }" :title="activityText(account, account.id)">
            {{ activityText(account, account.id) }}
          </div>
        </div>

        <div class="ops-area">
          <el-tooltip content="选择课程开始刷课" placement="top">
            <el-button
              type="primary"
              :icon="CaretRight"
              @click="$emit('start', account)"
            >刷课</el-button>
          </el-tooltip>
          <el-tooltip content="停止当前任务(断点续刷)" placement="top">
            <el-button
              type="warning"
              :icon="SwitchButton"
              :disabled="!['starting', 'running'].includes(statusOf(account.id).state)"
              @click="$emit('stop', account)"
            />
          </el-tooltip>
          <el-tooltip content="按上次课程与参数重新启动" placement="top">
            <el-button
              type="success"
              plain
              :icon="RefreshRight"
              :disabled="!account.course_ids?.length"
              @click="$emit('restart', account)"
            />
          </el-tooltip>
          <el-tooltip content="实时运行日志" placement="top">
            <el-button :icon="Document" @click="$emit('logs', account)" />
          </el-tooltip>
          <el-tooltip content="编辑账号信息与默认参数" placement="top">
            <el-button :icon="EditPen" @click="$emit('edit', account)" />
          </el-tooltip>
          <el-tooltip content="删除账号" placement="top">
            <el-button type="danger" :icon="Delete" @click="$emit('remove', account)" />
          </el-tooltip>
          <el-button v-if="statusOf(account.id).needs_attention" type="danger" :icon="Camera"
                     :plain="statusOf(account.id).blocked_reason !== 'face'"
                     @click="$emit('face', account)">
            {{ statusOf(account.id).blocked_reason === 'face' ? '去扫码' : '人脸' }}
          </el-button>
        </div>
      </div>

      <!-- 展开详情: 章节树 -->
      <div v-if="expandedIds.has(account.id)" class="detail-panel">
        <div class="detail-card">
          <div class="detail-title" style="display: flex; align-items: center; gap: 8px">
            章节进度
            <el-button size="small" :icon="Refresh" circle :loading="treeLoading[account.id]" @click="loadTree(account.id, true)" />
            <span class="muted">
              {{ jobsLoading[account.id] ? '任务点批量加载中, 完成后章节即点即开...' : '绿色已完成 · 高亮为当前章节 · 点章节看任务点' }}
            </span>
          </div>
          <!-- v-loading 放在不滚动的外层, spinner 固定在可视区不随内容滚动 -->
          <div class="tree-wrap" v-loading="treeLoading[account.id]">
            <div class="tree-box" :data-account="account.id">
            <div v-if="!(treeData[account.id]?.length)" class="muted" style="padding: 12px">
              {{ account.course_ids?.length ? '正在加载章节树...' : '该账号还没有发起过刷课（无课程记忆）' }}
            </div>
            <div v-for="course in treeData[account.id] ?? []" :key="course.courseId" class="course-block">
              <div class="course-head" @click="toggleCourse(account.id, course.courseId)">
                <span class="course-chevron">{{ courseOpen[`${account.id}/${course.courseId}`] ? '▾' : '▸' }}</span>
                <span class="course-name">{{ course.title || `课程 ${course.courseId}` }}</span>
                <span class="muted">{{ course.chapters.filter((c) => c.done).length }}/{{ course.chapters.length }} 章节完成</span>
              </div>
              <template v-if="courseOpen[`${account.id}/${course.courseId}`]">
              <template v-for="ch in course.chapters" :key="ch.id">
                <div
                  class="chapter-item"
                  :class="{ done: ch.done, current: ch.title === statusOf(account.id).current_chapter, open: chapterOpen[`${account.id}/${ch.id}`] }"
                  @click="toggleChapter(account.id, course.courseId, ch)"
                >
                  <span class="chapter-chevron">{{ chapterOpen[`${account.id}/${ch.id}`] ? '▾' : '▸' }}</span>
                  <span class="chapter-flag">{{ ch.done ? '✓' : '·' }}</span>
                  <span class="chapter-title">{{ ch.title }}</span>
                  <span v-if="ch.title === statusOf(account.id).current_chapter" class="current-tag">刷这里</span>
                </div>
                <div v-if="chapterOpen[`${account.id}/${ch.id}`]" class="jobs-box">
                  <div v-if="chapterLoading[`${account.id}/${ch.id}`]" class="muted" style="padding: 2px 0 2px 40px">加载任务点...</div>
                  <template v-else-if="(ch.jobs ?? chapterJobs[`${account.id}/${ch.id}`])?.length">
                    <div
                      v-for="(job, ji) in ch.jobs ?? chapterJobs[`${account.id}/${ch.id}`]"
                      :key="ji"
                      class="job-item"
                      :class="{ done: job.done, playing: !!playingVideo(account.id, job.name) }"
                    >
                      <span class="job-icon">{{ jobTypeMeta[job.type]?.icon || '·' }}</span>
                      <span class="job-type">{{ jobTypeMeta[job.type]?.label || job.type }}</span>
                      <span class="job-name" :title="job.name">{{ job.name || '（未命名）' }}</span>
                      <template v-if="playingVideo(account.id, job.name)">
                        <el-progress
                          :percentage="playingVideo(account.id, job.name)!.percent"
                          :stroke-width="6"
                          :show-text="false"
                          class="job-progress"
                        />
                        <span class="job-progress-text">{{ playingVideo(account.id, job.name)!.percent }}%</span>
                      </template>
                      <span v-else class="job-flag">{{ job.done ? '✓' : '' }}</span>
                    </div>
                  </template>
                  <div v-else class="muted" style="padding: 2px 0 2px 40px">该章节没有任务点</div>
                </div>
              </template>
              </template>
            </div>
            </div>
          </div>
        </div>

        <div v-if="statusOf(account.id).videos?.length" class="detail-card">
          <div class="detail-title">正在观看</div>
          <div v-for="video in statusOf(account.id).videos" :key="video.name" class="detail-video">
            <span class="video-name" :title="video.name">{{ video.name }}</span>
            <el-progress :percentage="video.percent" :stroke-width="10" class="detail-video-bar" />
            <span class="muted">{{ video.percent }}% · {{ video.pos }}/{{ video.total }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.account-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.empty-tip {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 32px;
  text-align: center;
  color: #909399;
}

/* 卡片 */
.account-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  overflow: hidden;
  transition: box-shadow 0.2s;
}
.account-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}
.account-card.expanded {
  border-color: #d9ecff;
}

/* 卡片头 */
.card-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  cursor: pointer;
  user-select: none;
}

.avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  color: #fff;
  font-weight: 600;
  font-size: 17px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.id-block {
  width: 130px;
  flex: none;
}
.label-line {
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.phone-line {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.status-block {
  width: 84px;
  flex: none;
}
.blocked-line {
  font-size: 11px;
  color: #f56c6c;
  margin-top: 3px;
}

.progress-block {
  flex: 1;
  min-width: 0;
  position: relative;
  align-self: stretch;
  min-height: 52px;
}
/* 进度条绝对居中于卡片纵向中线, 动态行紧贴其下 */
.progress-row {
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
}
.progress-bar {
  flex: 1;
  min-width: 0;
}
.progress-text {
  flex: none;
  font-size: 12px;
  color: #606266;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.activity-line {
  position: absolute;
  top: calc(50% + 12px);
  left: 0;
  right: 0;
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.activity-line.is-error {
  color: #f56c6c;
}

.ops-area {
  display: flex;
  align-items: center;
  gap: 0;
  flex: none;
}
.ops-area .el-button {
  margin: 0;
}
.ops-area .el-button + .el-button {
  margin-left: 6px;
}

/* 展开详情 */
.detail-panel {
  padding: 4px 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  cursor: default;
  background: #fafbfc;
  border-top: 1px solid #ebeef5;
}
.detail-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 16px;
  margin-top: 12px;
}
.detail-title {
  font-weight: 600;
  margin-bottom: 10px;
  color: #303133;
}

/* 章节树 */
/* v-loading 容器: 不滚动, spinner 固定在可视区 */
.tree-wrap {
  position: relative;
}
.tree-box {
  max-height: 300px;
  overflow: auto;
}
.course-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.course-block + .course-block {
  margin-top: 10px;
}
.course-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  border-bottom: 1px solid #e4e7ed;
  margin-bottom: 4px;
  cursor: pointer;
  user-select: none;
}
.course-head:hover {
  background: #f0f2f5;
}
.course-chevron {
  width: 14px;
  text-align: center;
  flex: none;
  color: #909399;
  font-size: 11px;
}
.course-name {
  flex: 1;
  font-weight: 600;
  color: #303133;
  font-size: 13px;
  text-align: left;
}
.chapter-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border-radius: 5px;
  font-size: 13px;
  color: #606266;
  cursor: pointer;
  user-select: none;
}
.chapter-item:hover {
  background: #f0f2f5;
}
.chapter-item.done {
  color: #67c23a;
}
.chapter-item.current {
  background: #ecf5ff;
  color: #409eff;
  font-weight: 600;
}
.chapter-chevron {
  width: 14px;
  text-align: center;
  flex: none;
  color: #909399;
  font-size: 11px;
}
.chapter-flag {
  width: 14px;
  text-align: center;
  flex: none;
}
.chapter-title {
  flex: 1;
}
.current-tag {
  font-size: 11px;
  color: #409eff;
  border: 1px solid #409eff;
  border-radius: 3px;
  padding: 0 4px;
  flex: none;
}

/* 章节下任务点 */
.jobs-box {
  padding: 0 0 4px 0;
}
.job-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 10px 2px 40px;
  font-size: 12px;
  color: #606266;
}
.job-item.done {
  color: #67c23a;
}
.job-item.playing {
  color: #409eff;
}
.job-icon {
  flex: none;
  width: 14px;
  text-align: center;
}
.job-type {
  flex: none;
  color: #909399;
  width: 32px;
}
.job-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.job-flag {
  flex: none;
  width: 14px;
}
.job-progress {
  width: 90px;
  flex: none;
}
.job-progress-text {
  flex: none;
  font-size: 11px;
  width: 34px;
  text-align: right;
}

/* ---------- 移动端: 卡片头两行网格, 操作区独占一行 ---------- */
@media (max-width: 768px) {
  .card-head {
    flex-wrap: wrap;
    gap: 10px;
    padding: 12px;
  }
  .id-block {
    flex: 1;
    min-width: 0;
  }
  .status-block {
    width: auto;
  }
  /* 进度块独占整行, 恢复文档流(取消绝对定位) */
  .progress-block {
    position: static;
    flex-basis: 100%;
    order: 3;
    min-height: 0;
  }
  .progress-row {
    position: static;
    transform: none;
  }
  .activity-line {
    position: static;
    margin-top: 4px;
  }
  .ops-area {
    flex-basis: 100%;
    order: 4;
    flex-wrap: wrap;
    gap: 6px;
  }
  .ops-area .el-button {
    margin: 0 !important;
    flex: 1 1 calc(25% - 6px);
    padding-left: 8px;
    padding-right: 8px;
  }
  .ops-area :deep(.el-button span) {
    font-size: 13px;
  }
  /* 触屏高度 */
  .chapter-item,
  .course-head {
    min-height: 36px;
  }

  .detail-panel {
    padding: 4px 10px 12px;
  }
  .tree-box {
    max-height: 50vh;
  }
  .job-item {
    padding-left: 30px;
  }
  .detail-video .video-name {
    max-width: 100px;
  }
}

.detail-video {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.detail-video-bar {
  flex: 1;
}
.video-name {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: #606266;
  flex: none;
}
</style>
