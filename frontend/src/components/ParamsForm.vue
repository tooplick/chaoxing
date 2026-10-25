<script setup lang="ts">
import type { AccountParams } from '../types'
import { useIsMobile } from '../composables/useIsMobile'

const { isMobile } = useIsMobile()

defineProps<{ params: AccountParams }>()
defineEmits<{ (e: 'update:params', value: AccountParams): void }>()
</script>

<template>
  <el-form
    :label-position="isMobile ? 'top' : 'left'"
    :label-width="isMobile ? '' : '140px'"
    size="default"
    @submit.prevent
  >
    <el-form-item label="视频倍速">
      <el-slider
        :model-value="params.speed"
        :min="1"
        :max="2"
        :step="0.25"
        :show-input="true"
        :show-input-controls="false"
        style="width: 100%"
        @update:model-value="(v: any) => $emit('update:params', { ...params, speed: Number(v) })"
      />
    </el-form-item>

    <el-form-item label="并发章节数">
      <el-input-number
        :model-value="params.jobs"
        :min="1"
        :max="16"
        @update:model-value="(v: any) => $emit('update:params', { ...params, jobs: Number(v) })"
      />
      <span class="muted" style="margin-left: 10px">同 IP 多账号时建议保守设置</span>
    </el-form-item>

    <el-form-item label="关闭任务点处理">
      <el-select
        :model-value="params.notopen_action"
        style="width: 200px"
        @update:model-value="(v: any) => $emit('update:params', { ...params, notopen_action: v })"
      >
        <el-option label="重试 (默认)" value="retry" />
        <el-option label="跳过继续" value="continue" />
      </el-select>
    </el-form-item>

    <el-form-item label="重试间隔 (秒)">
      <el-input-number
        :model-value="params.retry_interval"
        :min="0.5"
        :max="60"
        :step="0.5"
        @update:model-value="(v: any) => $emit('update:params', { ...params, retry_interval: Number(v) })"
      />
    </el-form-item>

    <el-form-item label="章节检测自动重做">
      <el-switch
        :model-value="params.work_redo_enabled"
        @update:model-value="(v: any) => $emit('update:params', { ...params, work_redo_enabled: !!v })"
      />
      <el-input-number
        v-if="params.work_redo_enabled"
        :model-value="params.work_max_retries"
        :min="1"
        :max="10"
        style="margin-left: 12px"
        @update:model-value="(v: any) => $emit('update:params', { ...params, work_max_retries: Number(v) })"
      />
      <span class="muted" style="margin-left: 10px">仅允许作答一次的课程请保持关闭</span>
    </el-form-item>

    <el-form-item label="增加章节学习次数">
      <el-switch
        :model-value="params.add_learning_count"
        @update:model-value="(v: any) => $emit('update:params', { ...params, add_learning_count: !!v })"
      />
      <el-input-number
        v-if="params.add_learning_count"
        :model-value="params.target_count"
        :min="1"
        :max="10000"
        style="margin-left: 12px"
        @update:model-value="(v: any) => $emit('update:params', { ...params, target_count: Number(v) })"
      />
      <span class="muted" style="margin-left: 10px">刷完任务点后追加执行</span>
    </el-form-item>
  </el-form>
</template>
