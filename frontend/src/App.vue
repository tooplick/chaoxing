<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from './api'
import LoginView from './views/LoginView.vue'
import DashboardView from './views/DashboardView.vue'
import SettingsView from './views/SettingsView.vue'
import { useAccounts } from './composables/useAccounts'

const initialized = ref(true)
const loggedIn = ref(false)
const view = ref<'dashboard' | 'settings'>('dashboard')

const { startPolling, stopPolling } = useAccounts()

async function checkAuth() {
  try {
    const state = await api.authState()
    initialized.value = state.initialized
    loggedIn.value = state.logged_in
    if (loggedIn.value) startPolling()
  } catch {
    loggedIn.value = false
  }
}

function onLoggedIn() {
  loggedIn.value = true
  startPolling()
}

async function logout() {
  try {
    await api.authLogout()
  } finally {
    loggedIn.value = false
    stopPolling()
  }
}

function onAuthExpired() {
  loggedIn.value = false
  stopPolling()
}

onMounted(() => {
  checkAuth()
  window.addEventListener('auth-expired', onAuthExpired)
})
onBeforeUnmount(() => window.removeEventListener('auth-expired', onAuthExpired))
</script>

<template>
  <LoginView v-if="!loggedIn" :initialized="initialized" @logged-in="onLoggedIn" />
  <el-container v-else class="layout">
    <el-header class="layout-header" height="56px">
      <div class="brand">chaoxing 多账号刷课平台</div>
      <el-menu mode="horizontal" :default-active="view" class="nav" @select="(k: any) => (view = k)">
        <el-menu-item index="dashboard">仪表盘</el-menu-item>
        <el-menu-item index="settings">设置</el-menu-item>
      </el-menu>
      <el-button text type="danger" @click="logout">
        退出<span class="hide-mobile">登录</span>
      </el-button>
    </el-header>
    <el-main>
      <DashboardView v-if="view === 'dashboard'" />
      <SettingsView v-else />
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100%;
}
.layout-header {
  display: flex;
  align-items: center;
  gap: 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}
.brand {
  font-weight: 600;
  font-size: 16px;
  white-space: nowrap;
}
.nav {
  flex: 1;
  border-bottom: none;
  min-width: 0;
  overflow-x: auto;
}

/* ---------- 移动端 ---------- */
@media (max-width: 768px) {
  .layout-header {
    gap: 8px;
    padding: 0 10px;
  }
  .brand {
    font-size: 14px;
  }
  .nav :deep(.el-menu-item) {
    padding: 0 10px;
  }
  .layout-header :deep(.el-button) {
    padding: 8px;
    margin-left: 0;
  }
}
</style>
