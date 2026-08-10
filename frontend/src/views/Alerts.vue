<script setup>
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import http from '../api/client'

// 告警数据（实时计算，不落库）
const data = ref({ generated_at: null, total: 0, by_level: { critical: 0, warning: 0, info: 0 }, alerts: [] })
const rules = ref([])
const loading = ref(false)
const activeRules = ref([]) // 折叠面板：默认收起

let timer = null

// 级别元信息：文案 + 颜色（对齐设备状态色板）
const LEVEL = {
  critical: { label: '严重', type: 'danger', color: '#ff3b30' },
  warning: { label: '警告', type: 'warning', color: '#ff9f0a' },
  info: { label: '提示', type: 'info', color: '#8e8e93' },
}

const alerts = computed(() => data.value.alerts || [])
const byLevel = computed(() => data.value.by_level || { critical: 0, warning: 0, info: 0 })

function fmtTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

async function load() {
  loading.value = true
  try {
    const { data: d } = await http.get('/alerts/current')
    data.value = d
  } finally {
    loading.value = false
  }
}

async function loadRules() {
  const { data: d } = await http.get('/alerts/rules')
  rules.value = d.rules || []
}

onMounted(() => {
  load()
  loadRules()
  timer = setInterval(load, 5000) // 5s 自动刷新
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page alerts">
    <!-- Page Header -->
    <div class="page-header">
      <div class="page-title">告警监控</div>
      <div class="page-header-right">
        <el-button :icon="'Setting'" @click="activeRules = activeRules.includes('rules') ? [] : ['rules']">告警规则</el-button>
      </div>
    </div>

    <!-- 4 Stat Cards -->
    <el-row :gutter="16" class="stat-row">
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-body">
            <div class="stat-tag-mini">今日</div>
            <div class="stat-value">{{ data.total }}</div>
            <div class="stat-label">今日告警</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-body">
            <div class="stat-tag-mini" :style="{ color: alerts.length > 0 ? 'var(--warning)' : 'var(--success)' }">
              {{ alerts.length > 0 ? '待处理' : '正常' }}
            </div>
            <div class="stat-value">{{ (byLevel.critical || 0) + (byLevel.warning || 0) }}</div>
            <div class="stat-label">待处理</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-body">
            <div class="stat-tag-mini" style="color: var(--success)">已恢复</div>
            <div class="stat-value">{{ Math.max(0, data.total - alerts.length) }}</div>
            <div class="stat-label">已恢复</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-body">
            <div class="stat-tag-mini" style="color: var(--success)">生效中</div>
            <div class="stat-value">{{ rules.length }}</div>
            <div class="stat-label">规则总数</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- Alert Table (when alerts exist) -->
    <el-card v-if="alerts.length" shadow="never" class="block">
      <div class="block-head">
        <span class="block-title">活跃告警 ({{ alerts.length }})</span>
        <span class="muted">更新于 {{ fmtTime(data.generated_at) }}</span>
      </div>
      <el-table :data="alerts" border stripe style="width: 100%" size="small">
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag :type="LEVEL[row.level]?.type || 'info'" size="small">
              {{ LEVEL[row.level]?.label || row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="设备" width="160">
          <template #default="{ row }">
            <span>{{ row.device_name }}</span>
            <span style="color: #8e8e93"> #{{ row.device_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="告警信息" min-width="260" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.ts) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Empty State (when no alerts) -->
    <div v-else class="empty-card">
      <div class="empty-icon" style="color: var(--success)">
        <svg viewBox="0 0 24 24" width="56" height="56" fill="currentColor" style="margin: 0 auto">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
        </svg>
      </div>
      <div class="empty-title">当前无活跃告警，系统运行正常</div>
      <div class="empty-desc">所有监控规则均未触发，您可以放心使用。</div>
    </div>

    <!-- Rules Collapse -->
    <el-collapse v-model="activeRules" style="margin-top: 18px">
      <el-collapse-item name="rules">
        <template #title>
          <span style="font-weight: 600">告警规则（{{ rules.length }}）</span>
        </template>
        <el-table :data="rules" border style="width: 100%" size="small">
          <el-table-column prop="name" label="规则" width="140" />
          <el-table-column label="级别" width="90">
            <template #default="{ row }">
              <el-tag :type="LEVEL[row.level]?.type || 'info'" size="small">
                {{ LEVEL[row.level]?.label || row.level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="300" />
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.alerts .muted {
  color: var(--text-muted);
  font-size: 12px;
}

/* Stat cards */
.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  background: #fff;
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  padding: 20px;
  transition: box-shadow 0.2s;
  height: 100%;
}
.stat-card:hover {
  box-shadow: var(--shadow-lg);
}
.stat-body {
  width: 100%;
}
.stat-tag-mini {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--text-primary);
}
.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

/* Block */
.block {
  margin-bottom: 16px;
  border-radius: var(--radius);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.block-title {
  font-weight: 600;
  font-size: 15px;
  color: var(--text-primary);
}

/* Empty state */
.empty-card {
  border: 2px dashed var(--card-border);
  border-radius: var(--radius);
  padding: 48px 32px;
  text-align: center;
  background: #fff;
}
.empty-card .empty-icon {
  margin-bottom: 16px;
}
.empty-card .empty-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.empty-card .empty-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 20px;
}
.history-link {
  color: #3b82f6;
  font-size: 14px;
  text-decoration: none;
  cursor: pointer;
}
.history-link:hover {
  text-decoration: underline;
}
</style>
