<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const props = defineProps<{ initialized: boolean }>()
const emit = defineEmits<{ (e: 'logged-in'): void }>()

const form = reactive({ password: '', confirm: '' })
const loading = ref(false)

async function submit() {
  if (!form.password) {
    ElMessage.warning('请输入口令')
    return
  }
  // 首次使用: 引导设置管理员口令
  if (!props.initialized) {
    if (form.password.length < 6) {
      ElMessage.warning('口令长度至少 6 位')
      return
    }
    if (form.password !== form.confirm) {
      ElMessage.warning('两次输入的口令不一致')
      return
    }
  }
  loading.value = true
  try {
    if (props.initialized) {
      await api.authLogin(form.password)
    } else {
      await api.authSetup(form.password)
    }
    emit('logged-in')
  } catch (err: any) {
    ElMessage.error(err.message ?? '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 class="title">chaoxing 多账号刷课平台</h2>
      <p class="muted">{{ initialized ? '请输入管理员口令' : '首次使用, 请设置管理员口令(至少 6 位)' }}</p>
      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="initialized ? '管理员口令' : '设置口令'"
            size="large"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-form-item v-if="!initialized">
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            placeholder="确认口令"
            size="large"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
          {{ initialized ? '登录' : '保存并进入' }}
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b4a6f 100%);
}
.login-card {
  width: 380px;
  padding: 8px 12px;
}
.title {
  margin: 4px 0 4px;
  text-align: center;
}
</style>
