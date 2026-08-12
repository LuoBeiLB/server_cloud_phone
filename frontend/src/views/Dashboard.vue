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

// KPI 磁贴（统一由 kpis 计算属性渲染，模板 v-for 复用）
const kpis = computed(() => {
  const o = overview.value
  const onlineRate = o.total_devices ? Math.round((o.running / o.total_devices) * 100) : 0
  return [
    { label: '设备总数', value: o.total_devices, color: 'var(--brand)', bg: 'var(--brand-bg)', icon: 'Iphone', sub: '全部云手机' },
    { label: '运行中', value: o.running, color: 'var(--success)', bg: '#dcfce7', icon: 'VideoPlay', sub: `在线率 ${onlineRate}%`, subColor: 'var(--success)' },
    { label: '已停止', value: o.stopped, color: 'var(--info)', bg: '#f1f5f9', icon: 'VideoPause', sub: '离线设备' },
    { label: '异常', value: o.error, color: 'var(--danger)', bg: '#fee2e2', icon: 'WarningFilled', sub: `${o.error} 条异常`, subColor: 'var(--danger)' },
    { label: '分组数', value: o.total_groups, color: 'var(--brand)', bg: 'var(--brand-bg)', icon: 'FolderOpened', sub: '设备分组' },
    { label: '在线 WS 客户端', value: o.ws_clients, color: 'var(--warning)', bg: '#fef3c7', icon: 'Connection', sub: '实时连接' },
  ]
})

// 状态分段条（stacked bar）
const statusSegments = computed(() => {
  const o = overview.value
  const total = o.total_devices || 0
  const max = Math.max(1, o.running || 0, o.stopped || 0, o.creating || 0, o.error || 0)
  const short = { running: '在线', stopped: '离线', creating: '维护', error: '告警' }
  return ['running', 'stopped', 'creating', 'error'].map((k) => ({
    key: k,
    label: STATUS_META[k].label,
    short: short[k],
    color: STATUS_META[k].color,
    count: o[k] || 0,
    pct: total ? ((o[k] || 0) / total) * 100 : 0,
    height: o[k] ? Math.max(15, Math.round((o[k] / max) * 100)) : 0,
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

    <!-- KPI 磁贴 -->
    <div class="kpi-grid">
      <div v-for="k in kpis" :key="k.label" class="stat-card">
        <div class="stat-icon" :style="{ background: k.bg, color: k.color }">
          <el-icon :size="22"><component :is="k.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ k.value }}</div>
          <div class="stat-label">{{ k.label }}</div>
          <div class="stat-sub" v-if="k.sub" :style="{ color: k.subColor || 'var(--text-muted)' }">{{ k.sub }}</div>
        </div>
      </div>
    </div>

    <!-- 可视化模块：状态分布 + 机型排行 + 分组排行 -->
    <el-row :gutter="16" class="charts-row">
      <!-- 状态分布 -->
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="chart-card">
          <div class="block-head">
            <span class="block-title">状态分布 <span class="realtime-badge">实时</span></span>
          </div>
          <div class="bar-chart">
            <div class="bar-item" v-for="s in statusSegments" :key="s.key">
              <div class="bar-wrap">
                <span class="bar-val">{{ s.count }}</span>
                <div class="bar-col" :style="{ height: s.height + '%', background: s.color }"></div>
              </div>
              <div class="bar-label">{{ s.short }}</div>
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

    <!-- 最近活跃设备 -->
    <el-card shadow="never" class="block">
      <div class="block-head">
        <span class="block-title">最近活跃设备</span>
        <span class="device-total">共 {{ overview.recent_devices.length }} 台</span>
      </div>
      <el-table :data="overview.recent_devices" size="small" style="width: 100%">
        <el-table-column prop="name" label="设备名称" min-width="160" />
        <!-- <el-table-column label="型号" min-width="120">
          <template #default="{ row }">{{ row.model || '—' }}</template>
        </el-table-column>
        <el-table-column label="分组" min-width="120">
          <template #default="{ row }">{{ row.group_name || '—' }}</template>
        </el-table-column> -->
        <el-table-column label="状态" width="140">
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

/* ===== KPI 磁贴（自动填充，永不失衡） ===== */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
.stat-card {
  background: #fff;
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}
.stat-card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}
.stat-card:hover .stat-icon {
  transform: scale(1.08);
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===== 可视化卡片（三卡等高，底部对齐） ===== */
.charts-row {
  align-items: stretch;
  margin-bottom: 16px;
}
.charts-row :deep(.el-col) {
  display: flex;
}
.chart-card {
  flex: 1;
  width: 100%;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
}
.chart-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-shrink: 0;
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

/* ===== 状态分布柱状图（随卡片等高伸缩） ===== */
.bar-chart {
  flex: 1;
  min-height: 180px;
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
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

/* ===== 排行徽标 ===== */
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

/* ===== 空状态 ===== */
.empty-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 32px 0;
}

/* ===== 最近活跃表 ===== */
.block {
  margin-bottom: 16px;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}
.device-total {
  font-size: 12px;
  color: var(--text-muted);
}
.dashboard :deep(.el-table) {
  border-radius: var(--radius-sm);
  overflow: hidden;
}
</style>
