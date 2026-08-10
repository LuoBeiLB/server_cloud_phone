<script setup>
import { onMounted, onBeforeUnmount, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDevices } from '../stores/devices'
import PhoneFrame from '../components/PhoneFrame.vue'

const store = useDevices()
const router = useRouter()
const cols = ref(3) // 2/3/4 -> 2x2 / 3x3 / 4x4，或自定义 n×n（1–8）
const groupId = ref('')

// 网格列数：自定义输入可能被清空成 null，渲染时兜底到合法范围
const gridN = computed(() => Math.max(1, Math.min(8, Number(cols.value) || 1)))

const shown = computed(() => {
  let list = store.list
  if (groupId.value) list = list.filter((d) => d.group_id === groupId.value)
  return list
})

function resubscribe() {
  store.subscribePreviews(shown.value.map((d) => d.id), 1)
}

watch(shown, resubscribe)
watch(cols, resubscribe)

onMounted(async () => {
  await store.refresh()
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
        <el-radio-group v-model="cols">
          <el-radio-button :value="2">2 × 2</el-radio-button>
          <el-radio-button :value="3">3 × 3</el-radio-button>
          <el-radio-button :value="4">4 × 4</el-radio-button>
        </el-radio-group>

        <div class="custom-grid">
          <span class="muted">自定义</span>
          <el-input-number
            v-model="cols"
            :min="1"
            :max="8"
            size="small"
            controls-position="right"
            style="width: 96px"
          />
          <span class="muted">{{ gridN }} × {{ gridN }}</span>
        </div>
        <el-select v-model="groupId" placeholder="全部分组" clearable style="width: 150px">
          <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
        </el-select>
        <el-button type="primary" @click="resubscribe">刷新画面</el-button>
      </div>
    </div>

    <div class="grid" :style="{ gridTemplateColumns: `repeat(${gridN}, 1fr)` }">
      <div class="preview-card" v-for="d in shown" :key="d.id">
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
    <el-empty v-if="!shown.length" description="暂无设备，请先到「设备管理」批量建机" />
  </div>
</template>

<style scoped>
.custom-grid {
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
:deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background-color: var(--brand);
  border-color: var(--brand);
  color: #fff;
  box-shadow: -1px 0 0 0 var(--brand);
}
</style>
