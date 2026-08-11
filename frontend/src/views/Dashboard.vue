<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import http from '../api/client'

// 状态色板：与 App 全局状态色保持一致（styles.css 的 .dot.*）
const STATUS_META = {
  running: { label: '运行中', color: '#34c759' },
  stopped: { label: '已停止', color: '#8e8e93' },
  creating: { label: '创建中', color: '#ff9f0a' },
  error: { label: '异常', color: '#ff3b30' },
}

const overview = ref({
  total_devices: 0,
  running: 0,
  stopped: 0,
  error: 0,
  creating: 0,
  total_groups: 0,
  ws_clients: 0,
  unique_exit_ips: 0,
  by_group: [],
  model_distribution: [],
  recent_devices: [],
})

const loading = ref(false)
const errored = ref(false)
const lastUpdated = ref(null)
let timer = null

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/metrics/overview')
    overview.value = data
    lastUpdated.value = new Date()
    errored.value = false
  } catch (e) {
    // 保留上一次数据，标记异常；5s 后自动重试
    errored.value = true
  } finally {
    loading.value = false
  }
}

// KPI 磁贴
const kpis = computed(() => {
  const o = overview.value
  return [
    { key: 'total', label: '总设备', value: o.total_devices, color: '#007aff', icon: 'Iphone' },
    { key: 'running', label: '运行中', value: o.running, color: STATUS_META.running.color, icon: 'VideoPlay' },
    { key: 'stopped', label: '已停止', value: o.stopped, color: STATUS_META.stopped.color, icon: 'VideoPause' },
    { key: 'error', label: '异常', value: o.error, color: STATUS_META.error.color, icon: 'WarningFilled' },
    { key: 'groups', label: '分组数', value: o.total_groups, color: '#5856d6', icon: 'FolderOpened' },
    { key: 'ws', label: '在线 WS 客户端', value: o.ws_clients, color: '#ff9f0a', icon: 'Connection' },
  ]
})

// 状态分段条（stacked bar）
const statusSegments = computed(() => {
  const o = overview.value
  const total = o.total_devices || 0
  return ['running', 'stopped', 'creating', 'error']
    .map((k) => ({
      key: k,
      label: STATUS_META[k].label,
      color: STATUS_META[k].color,
      count: o[k] || 0,
      pct: total ? ((o[k] || 0) / total) * 100 : 0,
    }))
})

const maxModel = computed(() =>
  Math.max(1, ...overview.value.model_distribution.map((m) => m.count)),
)
const maxGroup = computed(() =>
  Math.max(1, ...overview.value.by_group.map((g) => g.count)),
)

const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }
const statusTagType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }

function fmtTime(d) {
  return d ? d.toLocaleTimeString('zh-CN', { hour12: false }) : '—'
}
function fmtDateTime(s) {
  if (!s) return '—'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  load()
  timer = setInterval(load, 5000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page dashboard">
    <!-- Page Header -->
    <div class="page-header">
      <div class="page-title">数据看板</div>
      <div class="page-header-right">
        <el-tag v-if="errored" type="danger" size="small" effect="plain">数据获取失败，正在重试…</el-tag>
        <span class="update-time">更新于 {{ fmtTime(lastUpdated) }}</span>
        <el-button type="primary" :icon="'Refresh'" :loading="loading" @click="load">刷新数据</el-button>
      </div>
    </div>

    <!-- 4 Stat Cards -->
    <el-row :gutter="16" class="stat-row">
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: var(--brand-bg); color: var(--brand)">
            <el-icon :size="22"><Iphone /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ overview.total_devices }}</div>
            <div class="stat-label">设备总数</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #dcfce7; color: var(--success)">
            <el-icon :size="22"><VideoPlay /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ overview.running }}</div>
            <div class="stat-label">在线</div>
            <div class="stat-sub" style="color: var(--success)">在线率 {{ overview.total_devices ? ((overview.running / overview.total_devices) * 100).toFixed(0) : 0 }}%</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #fef3c7; color: var(--warning)">
            <el-icon :size="22"><VideoPause /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ overview.stopped }}</div>
            <div class="stat-label">离线</div>
            <div class="stat-sub">离线设备</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #fee2e2; color: var(--danger)">
            <el-icon :size="22"><WarningFilled /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ overview.error }}</div>
            <div class="stat-label">告警</div>
            <div class="stat-sub" style="color: var(--danger)">{{ overview.error }}条异常</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: var(--brand-bg); color: var(--brand)">
            <el-icon :size="22"><FolderOpened /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ overview.total_groups }}</div>
            <div class="stat-label">分组数</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-card">
          <div class="stat-icon" style="background: #fef3c7; color: var(--warning)">
            <el-icon :size="22"><Connection /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ overview.ws_clients }}</div>
            <div class="stat-label">在线WS客户端</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 3 Visualization Modules -->
    <el-row :gutter="16" class="block">
      <!-- Status Distribution Bar Chart -->
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="chart-card">
          <div class="block-head">
            <span class="block-title">状态分布 <span class="realtime-badge">实时</span></span>
          </div>
          <div class="bar-chart">
            <div class="bar-item" v-for="s in statusSegments" :key="s.key">
              <div class="bar-wrap">
                <span class="bar-val">{{ s.count }}</span>
                <div
                  class="bar-col"
                  :style="{
                    height: s.count > 0
                      ? Math.max(15, Math.round(s.count / Math.max(overview.running || 0, overview.stopped || 0, overview.creating || 0, overview.error || 0, 1) * 100)) + '%'
                      : '0%',
                    background: s.color,
                  }"
                ></div>
              </div>
              <div class="bar-label">{{
                s.key === 'running' ? '在线' : s.key === 'stopped' ? '离线' : s.key === 'creating' ? '维护' : '告警'
              }}</div>
              <div class="bar-pct">{{ s.pct.toFixed(0) }}%</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- Model Ranking TOP5 -->
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="chart-card">
          <div class="block-head">
            <span class="block-title">机型排行TOP5</span>
          </div>
          <div class="hbar-list" v-if="overview.model_distribution.length">
            <div class="hbar-row" v-for="(m, i) in overview.model_distribution.slice(0, 5)" :key="m.model">
              <span class="rank-badge" :class="'rank-' + (i + 1)">{{ i + 1 }}</span>
              <span class="hbar-label" :title="m.model">{{ m.model }}</span>
              <div class="hbar-track">
                <div class="hbar-fill" :style="{ width: (m.count / maxModel) * 100 + '%' }"></div>
              </div>
              <span class="hbar-count">{{ m.count }}</span>
            </div>
          </div>
          <div class="empty-hint" v-else>暂无数据</div>
        </el-card>
      </el-col>

      <!-- Group Ranking TOP5 -->
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="chart-card">
          <div class="block-head">
            <span class="block-title">分组排行TOP5</span>
          </div>
          <div class="hbar-list" v-if="overview.by_group.length">
            <div class="hbar-row" v-for="(g, i) in overview.by_group.slice(0, 5)" :key="g.group_id ?? 'none'">
              <span class="rank-badge" :class="'rank-' + (i + 1)">{{ i + 1 }}</span>
              <span class="hbar-label" :title="g.name">{{ g.name }}</span>
              <div class="hbar-track">
                <div class="hbar-fill" :style="{ width: (g.count / maxGroup) * 100 + '%' }"></div>
              </div>
              <span class="hbar-count">{{ g.count }}</span>
            </div>
          </div>
          <div class="empty-hint" v-else>暂无数据</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Recent Active Devices Table -->
    <el-card shadow="never" class="block">
      <div class="block-head">
        <span class="block-title">最近活跃设备</span>
      </div>
      <el-table :data="overview.recent_devices" size="small" style="width: 100%">
        <el-table-column prop="name" label="设备名称" min-width="140" />
        <el-table-column label="型号" min-width="120">
          <template #default="{ row }">{{ row.model || '—' }}</template>
        </el-table-column>
        <el-table-column label="分组" min-width="120">
          <template #default="{ row }">{{ row.group_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType[row.status]" size="small">{{ statusText[row.status] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近活跃" min-width="180">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <template #empty>暂无设备</template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard .update-time {
  color: var(--text-muted);
  font-size: 12px;
}

/* Stat cards row */
.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  background: #fff;
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: box-shadow 0.2s;
  height: 100%;
}
.stat-card:hover {
  box-shadow: var(--shadow-lg);
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-body {
  min-width: 0;
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
  margin-top: 2px;
}
.stat-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* Chart cards */
.block {
  margin-bottom: 16px;
}
.chart-card {
  border-radius: var(--radius);
  height: 100%;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.block-title {
  font-weight: 600;
  font-size: 15px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.realtime-badge {
  font-size: 11px;
  color: var(--success);
  background: #dcfce7;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}

/* Bar chart */
.bar-chart {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 180px;
  padding: 10px 8px 0;
}
.bar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  height: 100%;
}
.bar-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  width: 100%;
}
.bar-val {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}
.bar-col {
  width: 36px;
  max-width: 50px;
  border-radius: 6px 6px 0 0;
  min-height: 4px;
  transition: height 0.4s ease;
}
.bar-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 8px;
}
.bar-pct {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* Rank badges */
.rank-badge {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
  color: #fff;
  background: var(--text-muted);
}
.rank-badge.rank-1 {
  background: var(--brand);
}
.rank-badge.rank-2 {
  background: #818cf8;
}
.rank-badge.rank-3 {
  background: #a5b4fc;
}

/* Empty hint */
.empty-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 40px 0;
}
</style>
