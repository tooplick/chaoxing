<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { api } from '../api'
import type { NotificationConfig, TikuConfig } from '../types'
import TikuForm from '../components/TikuForm.vue'
import { useIsMobile } from '../composables/useIsMobile'

const { isMobile } = useIsMobile()

const tiku = ref<TikuConfig>({})
const notification = reactive<NotificationConfig & {
  host?: string; port?: number | string; ssl?: boolean; username?: string; password?: string; sender?: string
}>({})
const tikuLoading = ref(true)
const savingTiku = ref(false)
const testingTiku = ref(false)
const savingNotification = ref(false)
const emailTestTo = ref('')
const testingEmail = ref(false)

onMounted(async () => {
  try {
    const [tikuRes, notificationRes] = await Promise.all([api.getTiku(), api.getNotification()])
    tiku.value = tikuRes.tiku ?? {}
    Object.assign(notification, notificationRes.notification ?? {})
    if (notification.provider === 'Email' && notification.port === undefined) notification.port = 465
    if (notification.provider === 'Email' && notification.ssl === undefined) notification.ssl = true
  } catch (err: any) {
    ElMessage.error(err.message ?? '加载设置失败')
  } finally {
    tikuLoading.value = false
  }
})

async function testEmail() {
  if (!emailTestTo.value.trim()) {
    ElMessage.warning('请先填写测试收件邮箱')
    return
  }
  testingEmail.value = true
  try {
    const res = await api.testEmail(emailTestTo.value.trim())
    if (res.ok) ElNotification({ title: '测试邮件已发送', message: `请查收 ${emailTestTo.value}`, type: 'success', duration: 5000 })
    else ElNotification({ title: '测试邮件发送失败', message: res.msg || '未知原因', type: 'error', duration: 8000, showClose: true })
  } catch (err: any) {
    ElNotification({ title: '测试邮件发送失败', message: err.message ?? '发送失败', type: 'error', duration: 8000, showClose: true })
  } finally {
    testingEmail.value = false
  }
}

async function saveTiku() {
  savingTiku.value = true
  try {
    await api.putTiku(tiku.value)
    ElMessage.success('题库配置已保存')
  } catch (err: any) {
    ElMessage.error(err.message ?? '保存失败')
  } finally {
    savingTiku.value = false
  }
}

async function testTiku() {
  testingTiku.value = true
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
        message: res.msg || '测试失败',
        type: 'error',
        duration: 8000,
        showClose: true,
      })
    }
  } catch (err: any) {
    ElNotification({
      title: '题库异常',
      message: err.message ?? '测试失败',
      type: 'error',
      duration: 8000,
      showClose: true,
    })
  } finally {
    testingTiku.value = false
  }
}

async function saveNotification() {
  savingNotification.value = true
  try {
    await api.putNotification({ ...notification })
    ElMessage.success('通知配置已保存')
  } catch (err: any) {
    ElMessage.error(err.message ?? '保存失败')
  } finally {
    savingNotification.value = false
  }
}
</script>

<template>
  <div class="page" v-loading="tikuLoading">
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header>
        <div class="card-header">
          <span>题库 / 大模型答题配置</span>
          <div>
            <el-button :loading="testingTiku" @click="testTiku">测试连接</el-button>
            <el-button type="primary" :loading="savingTiku" @click="saveTiku">保存</el-button>
          </div>
        </div>
      </template>
      <TikuForm v-model:tiku="tiku" />
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>通知配置 (任务完成/出错/人脸拦截时推送)</span>
          <el-button type="primary" :loading="savingNotification" @click="saveNotification">保存</el-button>
        </div>
      </template>
      <el-form
        :label-position="isMobile ? 'top' : 'left'"
        :label-width="isMobile ? '' : '150px'"
        style="max-width: 640px"
      >
        <el-form-item label="通知服务">
          <el-select v-model="notification.provider" clearable placeholder="不使用通知" style="width: 240px">
            <el-option label="邮件通知 (SMTP)" value="Email" />
            <el-option label="Server酱" value="ServerChan" />
            <el-option label="Qmsg酱" value="Qmsg" />
            <el-option label="Bark" value="Bark" />
            <el-option label="Telegram" value="Telegram" />
          </el-select>
          <span class="muted" style="margin-left: 10px">
            {{ notification.provider === 'Email' ? '推送到各账号「编辑账号」里填写的邮箱' : '推送到下方 URL' }}
          </span>
        </el-form-item>

        <template v-if="notification.provider === 'Email'">
          <el-form-item label="SMTP 服务器">
            <el-input v-model="notification.host" placeholder="如 smtp.qq.com / smtp.163.com" />
          </el-form-item>
          <el-form-item label="端口">
            <el-input v-model="notification.port" placeholder="SSL 常用 465, STARTTLS 常用 587" style="width: 220px" />
          </el-form-item>
          <el-form-item label="SSL">
            <el-switch v-model="notification.ssl" />
            <span class="muted" style="margin-left: 10px">465 选开(SSL), 587 选关(STARTTLS)</span>
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="notification.username" placeholder="邮箱账号" />
          </el-form-item>
          <el-form-item label="密码/授权码">
            <el-input v-model="notification.password" type="password" show-password placeholder="邮箱密码或 SMTP 授权码(QQ/163 用授权码)" />
          </el-form-item>
          <el-form-item label="发件人">
            <el-input v-model="notification.sender" placeholder="留空则用用户名; 可填昵称(自动带邮箱)或完整邮箱" />
          </el-form-item>
          <el-form-item label="发送测试">
            <div style="display: flex; gap: 8px; width: 100%">
              <el-input v-model="emailTestTo" placeholder="测试收件邮箱" style="flex: 1" />
              <el-button :loading="testingEmail" @click="testEmail">发送测试</el-button>
            </div>
            <span class="muted" style="width: 100%">先点右上角「保存」再测试; 各账号的收件邮箱在「编辑账号」里填写</span>
          </el-form-item>
        </template>

        <template v-else-if="notification.provider">
          <el-form-item label="推送 URL">
            <el-input v-model="notification.url" placeholder="各服务的推送地址, 见 config_template.ini 注释" />
          </el-form-item>
          <el-form-item v-if="notification.provider === 'Telegram'" label="Telegram chat_id">
            <el-input v-model="notification.tg_chat_id" />
          </el-form-item>
        </template>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
