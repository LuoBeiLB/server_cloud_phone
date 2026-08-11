<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { api } from '../api/client'

const ROOT = '/sdcard/'

const devices = ref([])
const deviceId = ref(null)
const path = ref(ROOT)
const items = ref([])
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref(null)

// 多选 & 分页
const selected = ref([])
const currentPage = ref(1)
const pageSize = ref(20)

// 目录排在前、文件在后，各自按名称排序，浏览更顺手
const sortedItems = computed(() =>
  [...items.value].sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
    return a.name.localeCompare(b.name)
  }),
)

const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return sortedItems.value.slice(start, start + pageSize.value)
})

// 已在根目录（/sdcard/ 或 /）时不允许再往上
const canUp = computed(() => {
  const p = path.value.replace(/\/+$/, '')
  return p !== '' && path.value !== ROOT
})

// 路径面包屑
const breadcrumbs = computed(() => {
  const parts = path.value.replace(/\/+$/, '').split('/').filter(Boolean)
  return parts
})

// 文件大小格式化
function formatSize(bytes) {
  if (bytes == null) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

// 文件类型标签
function fileType(name) {
  const ext = name.split('.').pop()?.toLowerCase()
  const types = {
    apk: { label: 'APK', color: '#22c55e', bg: 'rgba(34,197,94,.12)' },
    jpg: { label: 'IMG', color: '#f59e0b', bg: 'rgba(245,158,11,.12)' },
    jpeg: { label: 'IMG', color: '#f59e0b', bg: 'rgba(245,158,11,.12)' },
    png: { label: 'IMG', color: '#f59e0b', bg: 'rgba(245,158,11,.12)' },
    mp4: { label: 'MP4', color: '#8b5cf6', bg: 'rgba(139,92,246,.12)' },
    mp3: { label: 'MP3', color: '#ec4899', bg: 'rgba(236,72,153,.12)' },
    txt: { label: 'TXT', color: '#64748b', bg: 'rgba(100,116,139,.12)' },
    json: { label: 'JSON', color: '#3b82f6', bg: 'rgba(59,130,246,.12)' },
    zip: { label: 'ZIP', color: '#ef4444', bg: 'rgba(239,68,68,.12)' },
  }
  return types[ext] || { label: ext?.toUpperCase() || 'FILE', color: '#64748b', bg: 'rgba(100,116,139,.12)' }
}

function joinPath(dir, name) {
  return dir.replace(/\/+$/, '') + '/' + name
}

async function loadDevices() {
  try {
    const { data } = await api.listDevices()
    devices.value = data || []
    if (!deviceId.value && devices.value.length) {
      deviceId.value = devices.value[0].id
      await loadFiles()
    }
  } catch {
    ElMessage.error('设备列表获取失败')
  }
}

async function loadFiles() {
  if (deviceId.value == null) return
  loading.value = true
  try {
    const { data } = await http.get(`/devices/${deviceId.value}/files`, {
      params: { path: path.value },
    })
    items.value = data.items || []
    currentPage.value = 1
    selected.value = []
  } catch (e) {
    items.value = []
    ElMessage.error(e?.response?.data?.detail || '目录读取失败')
  } finally {
    loading.value = false
  }
}

function onDeviceChange() {
  path.value = ROOT
  loadFiles()
}

function enter(item) {
  if (!item.is_dir) return
  path.value = joinPath(path.value, item.name) + '/'
  loadFiles()
}

function goUp() {
  if (!canUp.value) return
  const p = path.value.replace(/\/+$/, '')
  const idx = p.lastIndexOf('/')
  path.value = idx <= 0 ? '/' : p.slice(0, idx + 1)
  loadFiles()
}

function goHome() {
  path.value = ROOT
  loadFiles()
}

function goToCrumb(idx) {
  const parts = breadcrumbs.value
  path.value = '/' + parts.slice(0, idx + 1).join('/') + '/'
  loadFiles()
}

function triggerUpload() {
  if (deviceId.value == null) {
    ElMessage.warning('请先选择设备')
    return
  }
  fileInput.value?.click()
}

async function onFilePicked(e) {
  const f = e.target.files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  fd.append('remote_dir', path.value)

  uploading.value = true
  try {
    await http.post(`/devices/${deviceId.value}/files/upload`, fd)
    ElMessage.success(`已上传 ${f.name}`)
    loadFiles()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
    e.target.value = '' // 重置以便同名文件可再次选择
  }
}

async function download(item) {
  const remote = joinPath(path.value, item.name)
  try {
    const { data } = await http.get(`/devices/${deviceId.value}/files/download`, {
      params: { path: remote },
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([data]))
    const a = document.createElement('a')
    a.href = url
    a.download = item.name
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    ElMessage.success(`已下载 ${item.name}`)
  } catch {
    ElMessage.error('下载失败')
  }
}

async function remove(item) {
  const remote = joinPath(path.value, item.name)
  try {
    await ElMessageBox.confirm(`确认删除「${item.name}」？此操作不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await http.delete(`/devices/${deviceId.value}/files`, { params: { path: remote } })
    ElMessage.success('已删除')
    loadFiles()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '删除失败')
  }
}

function newFolder() {
  ElMessage.info('新建文件夹功能开发中')
}

onMounted(loadDevices)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">文件互传</div>
      <div class="page-header-right">
        <el-button :icon="'FolderAdd'" @click="newFolder">新建文件夹</el-button>
        <el-button type="primary" :icon="'Upload'" :loading="uploading" @click="triggerUpload">上传文件</el-button>
      </div>
    </div>

    <div class="toolbar">
      <el-select
        v-model="deviceId"
        placeholder="全部设备"
        size="default"
        style="width: 220px"
        filterable
        @change="onDeviceChange"
      >
        <el-option v-for="d in devices" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
    </div>

    <!-- 路径面包屑 -->
    <div class="pathbar">
      <el-button :icon="'HomeFilled'" size="small" text @click="goHome">根目录</el-button>
      <template v-for="(crumb, i) in breadcrumbs" :key="i">
        <el-icon class="path-sep"><ArrowRight /></el-icon>
        <el-button size="small" text @click="goToCrumb(i)">{{ crumb }}</el-button>
      </template>
      <el-button :icon="'Top'" size="small" text :disabled="!canUp" @click="goUp">上级</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="pagedItems"
      border
      stripe
      size="default"
      style="width: 100%"
      @selection-change="selected = $event"
    >
      <el-table-column type="selection" width="45" />
      <el-table-column label="名称" min-width="300">
        <template #default="{ row }">
          <span
            :class="{ 'dir-name': row.is_dir }"
            :style="row.is_dir ? 'cursor:pointer' : ''"
            @click="enter(row)"
          >
            <el-icon v-if="row.is_dir" style="vertical-align: -2px; margin-right: 6px; color: var(--warning)"><Folder /></el-icon>
            <el-icon v-else style="vertical-align: -2px; margin-right: 6px; color: var(--text-secondary)"><Document /></el-icon>
            {{ row.name }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="120">
        <template #default="{ row }">
          <span v-if="row.is_dir" style="color: var(--text-muted)">—</span>
          <span v-else>
            <span
              class="file-type-tag"
              :style="{ color: fileType(row.name).color, background: fileType(row.name).bg }"
            >{{ fileType(row.name).label }}</span>
            <span style="margin-left: 6px; color: var(--text-secondary)">{{ formatSize(row.size) }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="修改时间" width="180">
        <template #default="{ row }">
          <span style="color: var(--text-muted)">{{ row.modified || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" align="right">
        <template #default="{ row }">
          <template v-if="row.is_dir">
            <el-button size="small" text type="primary" @click="enter(row)">进入</el-button>
          </template>
          <template v-else>
            <el-button size="small" text type="primary" @click="download(row)">下载</el-button>
          </template>
          <el-button size="small" text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-bar">
      <span class="total-text">共 {{ sortedItems.length }} 个项目</span>
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="sortedItems.length"
        layout="prev, pager, next"
        background
      />
    </div>

    <input ref="fileInput" type="file" style="display: none" @change="onFilePicked" />
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
  margin-bottom: 14px;
}
.pathbar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 16px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid var(--card-border);
  border-radius: var(--radius-sm);
}
.path-sep {
  color: var(--text-muted);
  font-size: 12px;
}
.dir-name {
  color: var(--brand);
  font-weight: 500;
}
.file-type-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
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
:deep(.el-table) {
  border-radius: var(--radius-sm);
  overflow: hidden;
}
</style>
