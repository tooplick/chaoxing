<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import type { Account, AccountParams } from '../types'
import ParamsForm from './ParamsForm.vue'
import { useIsMobile } from '../composables/useIsMobile'

const { isMobile } = useIsMobile()

const props = defineProps<{ modelValue: boolean; account: Account | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'saved'): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const isEdit = computed(() => !!props.account)
const form = reactive({
  label: '',
  username: '',
  password: '',
  email: '',
  cookies: '',
})
const params = ref<AccountParams>({ ...defaultParams() })
const saving = ref(false)
const testing = ref(false)
const testResult = ref('')

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
  if (!open) return
  testResult.value = ''
  if (props.account) {
    form.label = props.account.label
    form.username = props.account.username
    form.password = props.account.password
    form.email = props.account.email ?? ''
    form.cookies = ''
    params.value = { ...defaultParams(), ...props.account.params }
  } else {
    Object.assign(form, { label: '', username: '', password: '', email: '', cookies: '' })
    params.value = defaultParams()
  }
})

async function save() {
  if (!form.username.trim()) {
    ElMessage.warning('手机号不能为空')
    return
  }
  if (!isEdit.value && !form.password.trim() && !form.cookies.trim()) {
    ElMessage.warning('请填写密码, 或粘贴 cookie 串')
    return
  }
  if (form.email.trim() && !form.email.includes('@')) {
    ElMessage.warning('邮箱格式无效')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await api.updateAccount(props.account!.id, {
        label: form.label.trim() || form.username.trim(),
        username: form.username.trim(),
        password: form.password.trim(),
        email: form.email.trim(),
        params: params.value,
        ...(form.cookies.trim() ? { cookies: form.cookies.trim() } : {}),
      })
    } else {
      await api.createAccount({
        label: form.label.trim() || form.username.trim(),
        username: form.username.trim(),
        password: form.password.trim(),
        email: form.email.trim(),
        cookies: form.cookies.trim(),
      })
      // 新账号保存默认参数
      const list = await api.listAccounts()
      const created = list.accounts.find((a) => a.username === form.username.trim())
      if (created) await api.updateAccount(created.id, { params: params.value })
    }
    ElMessage.success('已保存')
    visible.value = false
    emit('saved')
  } catch (err: any) {
    ElMessage.error(err.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

/** 保存后立即验证账号可登录(独立子进程真实登录一次) */
async function saveAndTest() {
  await save()
  if (!props.account) return
  testing.value = true
  testResult.value = '正在测试登录...'
  try {
    const res = await api.testAccount(props.account.id)
    testResult.value = res.ok ? `登录成功: ${res.name || '未知姓名'}` : `登录失败: ${res.msg}`
  } catch (err: any) {
    testResult.value = `登录失败: ${err.message}`
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <el-drawer v-model="visible" :title="isEdit ? '编辑账号' : '添加账号'" :size="isMobile ? '95%' : '480px'">
    <el-form
      :label-position="isMobile ? 'top' : 'left'"
      :label-width="isMobile ? '' : '90px'"
      @submit.prevent
    >
      <el-form-item label="备注">
        <el-input v-model="form.label" placeholder="例如: 张三" />
      </el-form-item>
      <el-form-item label="手机号">
        <el-input v-model="form.username" placeholder="学习通手机号" />
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="form.password" type="password" show-password placeholder="学习通密码" />
      </el-form-item>
      <el-form-item label="邮箱">
        <el-input v-model="form.email" placeholder="可选: 接收任务完成/人脸拦截通知" />
      </el-form-item>
      <el-form-item label="Cookie">
        <el-input
          v-model="form.cookies"
          type="textarea"
          :rows="2"
          placeholder="可选: 粘贴 cookie 串 (k=v;k=v), 用于代替密码登录; 留空不修改"
        />
      </el-form-item>
    </el-form>

    <el-divider content-position="left">默认刷课参数</el-divider>
    <ParamsForm v-model:params="params" />

    <div v-if="testResult" class="muted" style="margin-top: 8px">{{ testResult }}</div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button v-if="isEdit" :loading="testing" @click="saveAndTest">保存并测试登录</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-drawer>
</template>
