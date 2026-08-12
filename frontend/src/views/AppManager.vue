<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api/client'
import { api } from '../api/client'
import { useDevices } from '../stores/devices'

const store = useDevices()

// —— 单机应用管理 ——
const curDeviceId = ref(null)
const apps = ref([])
const loadingApps = ref(false)
const rowBusy = ref('') // 正在操作的「包名+动作」标记，用于按钮 loading

const appRows = computed(() => apps.value.map((p, i) => ({ i: i + 1, pkg: p })))

async function loadApps() {
  if (!curDeviceId.value) {
    apps.value = []
    return
  }
  loadingApps.value = true
  try {
    const { data } = await http.get(`/devices/${curDeviceId.value}/apps`)
    apps.value = data.apps || []
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载已装应用失败')
  } finally {
    loadingApps.value = false
  }
}

async function appAction(action, pkg, label, needConfirm) {
  if (needConfirm) {
    try {
      await ElMessageBox.confirm(`确认对「${pkg}」执行「${label}」？`, '确认操作', {
        type: 'warning',
        confirmButtonText: '确定',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  rowBusy.value = `${pkg}:${action}`
  try {
    await http.post(`/devices/${curDeviceId.value}/apps/${action}`, { package: pkg })
    ElMessage.success(`${label}成功`)
    if (action === 'uninstall') await loadApps()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || `${label}失败`)
  } finally {
    rowBusy.value = ''
  }
}

// —— 批量应用管理 ——
const batchSelected = ref([]) // 选中的设备行
const batchPkg = ref('')
const batchApk = ref('https://example.com/app.apk')

const batchIds = computed(() => batchSelected.value.map((d) => d.id))
const lastResult = ref(null) // {label, ok, failed, total}

// —— 批量选设备表：服务端分页（翻页才请求，不一次全量） ——
const allDevices = ref([])
const loadingDevices = ref(false)
const batchPage = ref(1)
const batchPageSize = ref(10)
const batchTotal = ref(0)
const batchPageDevices = computed(() => allDevices.value)

async function loadBatchDevices() {
  loadingDevices.value = true
  try {
    const { data } = await api.listDevices({ page: batchPage.value, page_size: batchPageSize.value })
    allDevices.value = data?.items || []
    batchTotal.value = data?.total || 0
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载设备列表失败')
  } finally {
    loadingDevices.value = false
  }
}

function onBatchPageChange(p) {
  batchPage.value = p
  loadBatchDevices()
}
function onBatchSizeChange(size) {
  batchPageSize.value = size
  batchPage.value = 1
  loadBatchDevices()
}

function onBatchSelect(rows) {
  batchSelected.value = rows
}

// —— 单机「搜索并选择设备」下拉：远程查询筛选。默认不查询任何数据，输入关键字才请求匹配的 10 条 ——
const deviceOptions = ref([])
const searchingDevices = ref(false)
let deviceSearchTimer = null
// 全量设备缓存：默认查询一次，之后打开下拉直接使用缓存，避免重复请求
let allDeviceOptions = []

async function loadDeviceOptions(q) {
  const kw = String(q || '').trim()
  searchingDevices.value = true
  try {
    if (kw) {
      const { data } = await api.listDevices({ q: kw, page: 1, page_size: 10 })
      deviceOptions.value = data?.items || []
    } else {
      if (!allDeviceOptions.length) {
        const { data } = await api.listDevices({ page: 1, page_size: 100 })
        allDeviceOptions = data?.items || []
      }
      deviceOptions.value = allDeviceOptions
    }
  } catch {
    deviceOptions.value = []
  } finally {
    searchingDevices.value = false
  }
}
function searchDeviceOptions(q) {
  clearTimeout(deviceSearchTimer)
  deviceSearchTimer = setTimeout(() => loadDeviceOptions(q), 300)
}

async function batchRun(action, label, payload, needConfirm) {
  if (!batchIds.value.length) return ElMessage.warning('请先勾选设备')
  if (needConfirm) {
    try {
      await ElMessageBox.confirm(
        `确认对已选 ${batchIds.value.length} 台设备执行「${label}」？`,
        '批量操作确认',
        { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  lastResult.value = null
  store.batchProgress = { action, done: 0, total: batchIds.value.length }
  try {
    const { data } = await http.post(`/apps/batch/${action}`, {
      device_ids: batchIds.value,
      ...payload,
    })
    store.batchProgress = { action, done: data.total, total: data.total }
    lastResult.value = { label, ok: data.ok, failed: data.failed, total: data.total }
    ElMessage.success(`${label}：成功 ${data.ok}/${data.total}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '批量操作失败')
  }
}

function batchAppAction(action, label, needConfirm) {
  if (!batchPkg.value) return ElMessage.warning('请输入包名')
  return batchRun(action, label, { package: batchPkg.value }, needConfirm)
}

function batchInstall() {
  if (!batchApk.value) return ElMessage.warning('请输入 APK URL')
  return batchRun('install', '批量安装', { apk_url: batchApk.value }, false)
}

// 新增：文件上传批量安装
const batchFile = ref(null)  // 选中的文件

async function batchInstallUpload() {
  if (!batchFile.value) return ElMessage.warning('请先选择 APK 文件')
  if (!batchIds.value.length) return ElMessage.warning('请先勾选设备')

  const formData = new FormData()
  formData.append('device_ids', batchIds.value.join(','))
  formData.append('file', batchFile.value)

  store.batchProgress = { action: '上传安装', done: 0, total: batchIds.value.length }

  try {
    const { data } = await http.post('/apps/batch/install-upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    store.batchProgress = { action: '上传安装', done: data.total, total: data.total }
    lastResult.value = { label: '上传安装', ok: data.ok, failed: data.failed, total: data.total }

    if (data.failed > 0) {
    ElMessage.error(`上传安装：成功 ${data.ok}/${data.total}，失败 ${data.failed}`)
} else {
    ElMessage.success(`上传安装完成：成功 ${data.ok}/${data.total}`)
}

  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '上传安装失败')
  }
}

const progressPct = computed(() => {
  const p = store.batchProgress
  return p && p.total ? Math.round((p.done / p.total) * 100) : 0
})

const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }
const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }

onMounted(async () => {
  await loadBatchDevices()
  loadDeviceOptions() // 默认查询一次全部设备，下拉打开即有数据
})
</script>

<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-title">应用管理</div>
      <div class="page-header-right">
        <el-button :icon="'Refresh'" :loading="loadingDevices" @click="loadBatchDevices">刷新设备</el-button>
      </div>
    </div>

    <!-- ① 单机应用管理 -->
    <el-card shadow="never" class="block app-card">
      <div class="block-head">
        <div class="block-title">
          <el-icon class="block-title-icon"><Box /></el-icon>
          <span>① 单机应用管理</span>
        </div>
        <div class="block-actions">
          <el-select
            v-model="curDeviceId"
            placeholder="搜索并选择设备"
            filterable
            remote
            clearable
            :loading="searchingDevices"
            :remote-method="searchDeviceOptions"
            style="width: 260px"
            @change="loadApps"
          >
            <el-option
              v-for="d in deviceOptions"
              :key="d.id"
              :label="`${d.name}（${statusText[d.status] || d.status}）`"
              :value="d.id"
            />
          </el-select>
          <el-button :icon="'Refresh'" :disabled="!curDeviceId" @click="loadApps">刷新应用</el-button>
          <el-tag type="info">共 {{ apps.length }} 个</el-tag>
        </div>
      </div>

      <el-table
        v-loading="loadingApps"
        :data="appRows"
        border
        stripe
        size="small"
        max-height="420"
      >
        <el-table-column prop="i" label="#" width="60" />
        <el-table-column prop="pkg" label="包名" min-width="240" />
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <div class="row-ops">
              <el-button
                size="small"
                link
                type="success"
                :icon="'VideoPlay'"
                :loading="rowBusy === `${row.pkg}:launch`"
                @click="appAction('launch', row.pkg, '启动')"
                >启动</el-button
              >
              <el-button
                size="small"
                link
                type="warning"
                :icon="'VideoPause'"
                :loading="rowBusy === `${row.pkg}:stop`"
                @click="appAction('stop', row.pkg, '强停')"
                >强停</el-button
              >
              <el-button
                size="small"
                link
                :icon="'Brush'"
                :loading="rowBusy === `${row.pkg}:clear`"
                @click="appAction('clear', row.pkg, '清数据', true)"
                >清数据</el-button
              >
              <el-button
                size="small"
                link
                type="danger"
                :icon="'Delete'"
                :loading="rowBusy === `${row.pkg}:uninstall`"
                @click="appAction('uninstall', row.pkg, '卸载', true)"
                >卸载</el-button
              >
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="curDeviceId ? '未获取到已装应用' : '请选择设备'" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- ② 批量应用管理 -->
    <el-card shadow="never" class="app-card">
      <div class="block-head">
        <div class="block-title">
          <el-icon class="block-title-icon"><Operation /></el-icon>
          <span>② 批量应用管理</span>
        </div>
      </div>
      <!-- 上：选择设备（全量，客户端分页） -->
      <div class="sub-title">
        <el-icon><Iphone /></el-icon>
        选择设备
      </div>
      <el-table
        v-loading="loadingDevices"
        :data="batchPageDevices"
        border
        stripe
        size="small"
        max-height="360"
        row-key="id"
        @selection-change="onBatchSelect"
      >
        <el-table-column type="selection" width="46" reserve-selection />
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType[row.status]" size="small">{{
              statusText[row.status] || row.status
            }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="IP" min-width="120">
          <template #default="{ row }">{{ row.fingerprint?.network?.exit_ip || '—' }}</template>
        </el-table-column>
        <template #empty>暂无设备</template>
      </el-table>
      <div class="pagination-bar">
        <el-tag type="primary" effect="plain">
          <el-icon style="vertical-align: -2px; margin-right: 4px"><CircleCheck /></el-icon>
          已选 {{ batchIds.length }} 台
        </el-tag>
        <el-pagination
          :current-page="batchPage"
          :page-size="batchPageSize"
          :total="batchTotal"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
          small
          @current-change="onBatchPageChange"
          @size-change="onBatchSizeChange"
        />
      </div>

      <!-- 下：批量操作 -->
      <el-divider content-position="left">批量操作</el-divider>

      <div class="sub-title">
        <el-icon><Cpu /></el-icon>
        按包名批量操作
      </div>
      <div class="ops-panel">
        <div class="batch-row">
          <el-input v-model="batchPkg" placeholder="包名，如 com.android.chrome" clearable class="batch-pkg" />
          <el-button type="success" @click="batchAppAction('launch', '批量启动', false)">批量启动</el-button>
          <el-button type="warning" @click="batchAppAction('stop', '批量强停', false)">批量强停</el-button>
          <el-button type="danger" @click="batchAppAction('uninstall', '批量卸载', true)">批量卸载</el-button>
        </div>
      </div>
      <div class="sub-title">
        <el-icon><Upload /></el-icon>
        批量安装 APK
      </div>
      <div class="ops-panel">
        <div class="batch-row">
          <el-input v-model="batchApk" placeholder="APK 下载地址（URL）" class="batch-apk">
            <template #append><el-button @click="batchInstall">批量安装</el-button></template>
          </el-input>
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".apk"
            :on-change="(f) => batchFile = f.raw"
            :on-remove="() => batchFile = null"
            class="batch-upload"
          >
            <el-button type="primary" plain>选择 APK 文件</el-button>
          </el-upload>
          <el-button
            type="primary"
            :disabled="!batchFile || !batchIds.length"
            @click="batchInstallUpload"
          >
            上传安装到已选设备（{{ batchIds.length }}台）
          </el-button>
        </div>
        <div class="el-upload__tip">
          选择一个本地 APK 文件，然后点击「上传安装到已选设备」安装到已勾选设备
        </div>
      </div>

      <el-progress
        v-if="store.batchProgress"
        :percentage="progressPct"
        :status="progressPct === 100 ? 'success' : ''"
        class="batch-progress"
      />
      <div v-if="store.batchProgress" class="batch-progress-text">
        {{ store.batchProgress.action }}：{{ store.batchProgress.done }} /
        {{ store.batchProgress.total }}
      </div>
      <div v-if="lastResult" class="result-tags">
        <el-tag type="success">{{ lastResult.label }} 成功 {{ lastResult.ok }}</el-tag>
        <el-tag v-if="lastResult.failed" type="danger">失败 {{ lastResult.failed }}</el-tag>
        <el-tag type="info">共 {{ lastResult.total }}</el-tag>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.block {
  margin-bottom: 14px;
}
/* 卡片：与其他页面统一的边框/圆角/阴影过渡 */
.app-card {
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  transition: box-shadow .2s;
}
.app-card:hover {
  box-shadow: var(--shadow-lg);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}
.block-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
  color: var(--text-primary);
}
.block-title-icon {
  color: var(--brand);
  font-size: 16px;
}
.block-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.sub-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  margin: 10px 0 8px;
}
.sub-title .el-icon {
  color: var(--brand);
}
.batch-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}
/* 批量操作面板：容器化，与其它页面卡片风格一致 */
.ops-panel {
  padding: 14px;
  background: var(--bg);
  border: 1px solid var(--card-border);
  border-radius: var(--radius-sm);
  margin-bottom: 4px;
}
.ops-panel .batch-row:last-child {
  margin-bottom: 0;
}
.ops-panel :deep(.el-upload__tip) {
  margin-top: 8px;
  color: var(--text-muted);
  line-height: 1.6;
}
.batch-pkg {
  width: 320px;
}
.batch-apk {
  width: 380px;
}
.batch-upload {
  display: inline-flex;
}
.batch-progress {
  margin-top: 16px;
}
.batch-progress-text {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}
.result-tags {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 14px;
  background: var(--bg);
  border: 1px solid var(--card-border);
  border-radius: var(--radius-sm);
}
.row-ops {
  display: flex;
  align-items: center;
  gap: 2px;
}
.row-ops .el-button + .el-button {
  margin-left: 0;
}
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}
:deep(.el-table) {
  border-radius: var(--radius-sm);
  overflow: hidden;
}
/* 表头：与其他页面一致的灰底加粗 */
:deep(.el-table__header th) {
  background: #f8fafc !important;
  color: var(--text-secondary);
  font-weight: 600;
}
</style>
