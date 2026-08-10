<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/client'

const logs = ref([])
const loading = ref(false)
let timer = null

const actionTagMap = {
  创建用户: 'success',
  修改用户: 'warning',
  删除用户: 'danger',
}

function actionType(action) {
  return actionTagMap[action] || 'info'
}

async function load(showLoading = false) {
  if (showLoading) loading.value = true
  try {
    const { data } = await http.get('/audit')
    logs.value = data
  } catch (e) {
    if (showLoading) ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

function fmt(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('zh-CN')
}

function detailText(d) {
  if (d === null || d === undefined || d === '') return '—'
  if (typeof d === 'string') return d
  try {
    return JSON.stringify(d)
  } catch {
    return String(d)
  }
}

onMounted(() => {
  load(true)
  timer = setInterval(() => load(false), 10000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span style="font-weight: 600">操作审计日志</span>
      <el-tag type="info" size="small" effect="plain" style="margin-left: 8px">每 10 秒自动刷新</el-tag>
      <div class="spacer"></div>
      <el-button @click="load(true)">刷新</el-button>
    </div>

    <el-table :data="logs" v-loading="loading" border stripe style="width: 100%" size="small">
      <el-table-column label="时间" width="190">
        <template #default="{ row }">{{ fmt(row.ts) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="操作者" width="150" />
      <el-table-column label="动作" width="140">
        <template #default="{ row }">
          <el-tag :type="actionType(row.action)" size="small">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target" label="对象" min-width="150" />
      <el-table-column label="详情" min-width="240">
        <template #default="{ row }">
          <span style="color: #909399">{{ detailText(row.detail) }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}
.spacer {
  flex: 1;
}
</style>
