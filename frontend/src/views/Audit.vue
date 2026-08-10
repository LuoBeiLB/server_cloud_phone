<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api/client'

const logs = ref([])
const loading = ref(false)
let timer = null

// 筛选
const dateRange = ref([])
const actionFilter = ref('')

// 分页
const currentPage = ref(1)
const pageSize = ref(10)

const actionTagMap = {
  创建: 'success',
  删除: 'danger',
  修改: 'primary',
  登录: '',
  创建用户: 'success',
  修改用户: 'primary',
  删除用户: 'danger',
  登录成功: '',
  登录失败: 'danger',
}

function actionType(action) {
  return actionTagMap[action] || 'info'
}

// 动作类型选项
const actionOptions = [
  { value: '', label: '全部动作' },
  { value: '创建', label: '创建' },
  { value: '修改', label: '修改' },
  { value: '删除', label: '删除' },
  { value: '登录', label: '登录' },
]

const filteredLogs = computed(() => {
  let result = logs.value
  if (actionFilter.value) {
    result = result.filter((l) => l.action?.includes(actionFilter.value))
  }
  if (dateRange.value && dateRange.value.length === 2) {
    const [start, end] = dateRange.value
    result = result.filter((l) => {
      if (!l.ts) return true
      const ts = new Date(l.ts)
      return ts >= new Date(start) && ts <= new Date(end)
    })
  }
  return result
})

const pagedLogs = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredLogs.value.slice(start, start + pageSize.value)
})

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

function queryLogs() {
  currentPage.value = 1
  load(true)
}

function exportAudit() {
  const rows = filteredLogs.value.map((l) => ({
    时间: fmt(l.ts),
    用户: l.username || '',
    动作: l.action || '',
    对象: l.target || '',
    IP: l.ip || '',
    详情: detailText(l.detail),
  }))
  const headers = Object.keys(rows[0] || { 时间: '', 用户: '', 动作: '', 对象: '', IP: '', 详情: '' })
  const csv = [
    headers.join(','),
    ...rows.map((r) => headers.map((h) => `"${String(r[h]).replace(/"/g, '""')}"`).join(',')),
  ].join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `audit-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('审计记录已导出')
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
    <div class="page-header">
      <div class="page-title">操作审计</div>
      <div class="page-header-right">
        <el-button :icon="'Refresh'" @click="load(true)">刷新</el-button>
        <el-button type="primary" :icon="'Download'" @click="exportAudit">导出审计</el-button>
      </div>
    </div>

    <el-table :data="filteredLogs" v-loading="loading" border stripe style="width: 100%" size="default">
      <el-table-column label="时间" width="190">
        <template #default="{ row }">
          <span style="color: var(--text-secondary)">{{ fmt(row.ts) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="140" />
      <el-table-column label="动作" width="120">
        <template #default="{ row }">
          <el-tag :type="actionType(row.action)" size="small" effect="light">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target" label="对象" min-width="160" />
      <el-table-column label="IP" width="140">
        <template #default="{ row }">
          <span style="color: var(--text-muted); font-family: monospace">{{ row.ip || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="详情" min-width="240">
        <template #default="{ row }">
          <span style="color: var(--text-muted)">{{ detailText(row.detail) }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.page {
  padding: 20px 24px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
}
.total-text {
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
