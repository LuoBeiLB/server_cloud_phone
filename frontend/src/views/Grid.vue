<script setup>
import { onMounted, onBeforeUnmount, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useDevices } from '../stores/devices'
import PhoneFrame from '../components/PhoneFrame.vue'

const store = useDevices()
const router = useRouter()
// 顶部布局合并为「1×1 ~ 8×8」下拉选择器（替代原来的 6 个独立按钮 / radio-group）
const gridN = ref(3)
const groupId = ref('')

// 网格下拉选项：1-8 共 8 档
const gridOptions = Array.from({ length: 8 }, (_, i) => i + 1)

// 设备列表：服务端分页懒加载（翻页/切分组才请求，不一次全量）
const devices = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(16)
const loading = ref(false)
async function loadDevices() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (groupId.value) params.group_id = groupId.value
    const { data } = await api.listDevices(params)
    devices.value = data?.items || []
    total.value = data?.total || 0
  } catch {
    devices.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function resubscribe() {
  store.subscribePreviews(devices.value.map((d) => d.id), 1)
}
function onPageChange(p) {
  page.value = p
  loadDevices()
}

watch(devices, resubscribe)
watch(gridN, resubscribe)
watch(groupId, () => {
  page.value = 1
  loadDevices()
})

onMounted(async () => {
  await loadDevices()
  await store.refreshGroups()
  resubscribe()
})
onBeforeUnmount(() => store.subscribePreviews([], 1))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">多画面预览</div>
      <div class="page-header-right">
        <!-- 顶部布局：1×1 ~ 8×8 一行下拉搞定（替代 6 个按钮 / 2x2/3x3/4x4 radio-group） -->
        <div class="grid-picker">
          <span class="muted">布局</span>
          <el-select v-model="gridN" style="width: 110px">
            <el-option v-for="n in gridOptions" :key="n" :label="`${n} × ${n}`" :value="n" />
          </el-select>
        </div>
        <el-select v-model="groupId" placeholder="全部分组" clearable style="width: 150px">
          <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
        </el-select>
        <el-button type="primary" @click="resubscribe">刷新画面</el-button>
      </div>
    </div>

    <div v-loading="loading" element-loading-text="加载中..." class="grid" :style="{ gridTemplateColumns: `repeat(${gridN}, 1fr)` }">
      <div class="preview-card" v-for="d in devices" :key="d.id">
        <div class="preview-status" :class="d.status">
          <span class="dot" :class="d.status"></span>
          {{ d.status === 'running' ? '在线' : d.status === 'error' ? '离线' : '忙碌' }}
        </div>
        <PhoneFrame
          :device="d"
          :frame="store.frames[d.id]"
          :last-action="store.lastActions[d.id]"
          @open="router.push(`/device/${d.id}`)"
        />
        <div class="preview-label">
          <span class="device-name">{{ d.name }}</span>
          <span class="device-group">{{ store.groups.find(g => g.id === d.group_id)?.name || '未分组' }}</span>
        </div>
      </div>
    </div>
    <div class="pagination-bar">
      <span class="page-info">共 {{ total }} 台设备</span>
      <el-pagination
        :current-page="page"
        :total="total"
        :page-size="pageSize"
        layout="prev, pager, next"
        background
        small
        @current-change="onPageChange"
      />
    </div>
    <el-empty v-if="!devices.length" description="暂无设备，请先到「设备管理」批量建机" />
  </div>
</template>

<style scoped>
.grid-picker {
  display: flex;
  align-items: center;
  gap: 8px;
}
.muted {
  color: var(--text-muted);
  font-size: 12px;
}
.preview-card {
  background: #fff;
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: box-shadow .2s;
  position: relative;
}
.preview-card:hover {
  box-shadow: var(--shadow-lg);
}
.preview-status {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 500;
  color: #fff;
  padding: 2px 8px;
  border-radius: 12px;
  background: rgba(0, 0, 0, .5);
}
.preview-status .dot {
  margin-right: 0;
}
.preview-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  font-size: 13px;
  background: #fff;
}
.device-name {
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.device-group {
  color: var(--text-muted);
  font-size: 12px;
  flex-shrink: 0;
  margin-left: 8px;
}
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
}
.page-info {
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
