<script setup>
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { useDevices, SKIN_PHASE_TEXT } from '../stores/devices'

const store = useDevices()
const router = useRouter()

const filter = ref({ q: '', status: '', group_id: '' })
const createDlg = ref(false)
const fpDlg = ref(false)
const fpDevice = ref(null)
const creating = ref(false)

// 一键换肤
const skinDlg = ref(false)
const skinThemes = ref([])
const skinForm = ref({ theme: 'ios', scope: 'all' })
const skinning = ref(false)
const form = ref({
  count: 10,
  name_prefix: '演示机',
  group_id: null,
  width: 720,
  height: 1280,
  dpi: 320,
  // 默认**不开网页**：新建的机器应该停在主屏，而不是一上来就是浏览器页面。
  // 需要开网页在「批量操控」里下发，或建机时手动填这里。
  target_url: '',
  auto_start: true,
})

// Server-side filtering and pagination: filter changes trigger API refresh
const page = computed(() => store.page)

function onFilterChange() {
  store.page = 1
  store.refresh({
    q: filter.value.q || undefined,
    status: filter.value.status || undefined,
    group_id: filter.value.group_id || undefined,
  })
}

// Debounce search input
let searchTimer = null
watch(() => filter.value.q, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(onFilterChange, 300)
})
watch(() => filter.value.status, onFilterChange)
watch(() => filter.value.group_id, onFilterChange)

function onPageChange(p) {
  store.page = p
  store.refresh({
    q: filter.value.q || undefined,
    status: filter.value.status || undefined,
    group_id: filter.value.group_id || undefined,
  })
}

// 每页条数：默认 20，可切 8/20/50/100
function onPageSizeChange(sz) {
  store.pageSize = sz
  store.page = 1
  store.refresh({
    q: filter.value.q || undefined,
    status: filter.value.status || undefined,
    group_id: filter.value.group_id || undefined,
  })
}

onMounted(async () => {
  // 默认每页 20 条（之前是默认 10）
  if (store.pageSize === 10) store.pageSize = 20
  store.page = 1
  store.refresh({
    q: filter.value.q || undefined,
    status: filter.value.status || undefined,
    group_id: filter.value.group_id || undefined,
  })
  store.refreshGroups()
  store.refreshSkinApplying()
  try {
    skinThemes.value = (await api.listSkinThemes()).data.themes
  } catch {
    skinThemes.value = [{ key: 'ios', label: 'iOS 风' }]
  }
})

const skinLabel = (k) => skinThemes.value.find((t) => t.key === k)?.label || k

async function applySkinRow(id, theme) {
  try {
    await api.applySkin(id, theme)
    ElMessage.success(`已换肤：${skinLabel(theme)} · 真机后台落地中，进度见「皮肤」列`)
    await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '换肤失败')
  }
}

function openSkinDlg() {
  // 勾选了设备就默认应用到「已选设备」；没勾选则回到「全部设备」
  skinForm.value.scope = store.allSelectedCount ? 'selected' : 'all'
  skinDlg.value = true
}

async function applySkinBatch() {
  const scope = skinForm.value.scope
  let ids = []
  if (scope === 'selected') {
    if (!store.allSelectedCount) return ElMessage.warning('尚未勾选设备，请先在列表中勾选要换肤的设备')
    ids = [...store.allSelectedIds]
  }
  // scope === 'all'：ids 保持空数组，后端会应用到全部设备
  skinning.value = true
  try {
    const r = await api.applySkinBatch(ids, skinForm.value.theme)
    ElMessage.success(
      `已为 ${r.data.count} 台设备换肤：${skinLabel(skinForm.value.theme)} · 真机逐台落地中，进度见「皮肤」列`,
    )
    skinDlg.value = false
    await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '换肤失败')
  } finally {
    skinning.value = false
  }
}

async function batchCreate() {
  creating.value = true
  store.creating = true
  try {
    await api.batchCreate(form.value)
    ElMessage.success(`已创建 ${form.value.count} 台云手机`)
    createDlg.value = false
    await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined })
    await store.refreshGroups()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
    store.creating = false
  }
}

async function act(fn, id, okMsg) {
  try {
    await fn(id)
    if (okMsg) ElMessage.success(okMsg)
    await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function rename(d) {
  let value
  try {
    // 用户点「取消」时 prompt 会 reject，那不是错误
    ;({ value } = await ElMessageBox.prompt('新名称', '重命名', { inputValue: d.name }))
  } catch {
    return
  }
  try {
    await api.updateDevice(d.id, { name: value })
  } catch {
    return // 失败提示由 api/client.js 的兜底统一给出；不要继续往下走假装成功
  }
  await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined })
  ElMessage.success('已重命名')
}

async function assignGroup(d, gid) {
  try {
    await api.updateDevice(d.id, { group_id: gid })
  } catch {
    await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined }) // 回滚界面上的乐观显示，避免看起来改成功了
    return
  }
  await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined })
  await store.refreshGroups()
}

// ---- 批量删除 ----
// 切后端 / 跑过冒烟测试后常留下几十台废设备，一台台点删除不可接受。
// 「已选」以 store.allSelectedIds 为单一事实源（跨页保留），表格内 reserve-selection 只是 UI 表现。
const selected = ref([]) // 当前页 el-table 内部的勾选（reserve-selection 跨页保留，仅 UI 用）
const deleting = ref(false)
const tableRef = ref(null)

// 同步：把 el-table 当前页选中的 + store 里所有「非当前页」已选 → 合并写到 store.allSelectedIds
// （确保 Batch.vue 跨页面读到的 N 台是全集，而不是只当前页）
function syncSelectionToStore() {
  // 当前页可见 id：store.list 的所有 id
  const currentPageIds = new Set(store.list.map((d) => d.id))
  const set = new Set()
  // 1) 当前页 el-table 勾选的全部纳入
  for (const d of selected.value) set.add(d.id)
  // 2) 保留 store 中所有「非当前页」已选（它们只可能在 store 里）
  for (const id of store.allSelectedIds) {
    if (!currentPageIds.has(id)) set.add(id)
  }
  store.setAllSelectedIds([...set])
}

function onSelectionChange(rows) {
  selected.value = rows
  syncSelectionToStore()
}

// 「全选所有页」：按 store.total 拉所有 id（全部分页+全部分组，绕过当前筛选）
// 简化版：直接用 store.total（API 已返回）。若有筛选条件，则用「全选所有页」+ 当前筛选
const selectingAll = ref(false)
async function selectAllPages() {
  if (!store.total) return ElMessage.warning('当前没有设备可全选')
  try {
    await ElMessageBox.confirm(
      `将从服务端拉取所有 ${store.total} 台设备的 id（应用当前筛选），并标记为已选。\n用于「批量操控」的 1 控 N 主控同步。`,
      '全选所有页',
      { type: 'info', confirmButtonText: '全选', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  selectingAll.value = true
  try {
    // 拉所有页（应用当前筛选），按后端 max page_size 分页循环取
    // 后端 page_size 上限通常 ≤100，单次 page_size=1000 会触发 422
    const ids = []
    const pageSize = 100
    let p = 1
    while (ids.length < store.total) {
      const { data } = await api.listDevices({
        page: p,
        page_size: pageSize,
        q: filter.value.q || undefined,
        status: filter.value.status || undefined,
        group_id: filter.value.group_id || undefined,
      })
      const items = Array.isArray(data) ? data : data.items || []
      if (items.length === 0) break
      ids.push(...items.map((d) => d.id))
      if (items.length < pageSize) break
      p += 1
      // 保险：最多循环 50 次（5000 台），防止后端 total 撒谎时死循环
      if (p > 50) break
    }
    store.setAllSelectedIds(ids)
    // 让 el-table 内部 reserve-selection 同步高亮（仅当前页可见的行会被勾上）
    selected.value = store.list.filter((d) => store.allSelectedIds.includes(d.id))
    tableRef.value?.clearSelection()
    // 等待 nextTick 再设勾选
    setTimeout(() => {
      for (const d of selected.value) tableRef.value?.toggleRowSelection(d, true)
    }, 0)
    ElMessage.success(`已全选 ${ids.length} 台`)
  } catch (e) {
    ElMessage.error(e?.friendly || '全选失败')
  } finally {
    selectingAll.value = false
  }
}

function clearAllSelection() {
  store.clearAllSelectedIds()
  selected.value = []
  tableRef.value?.clearSelection()
  ElMessage.success('已清空已选设备')
}

async function batchRemove() {
  if (!store.allSelectedCount) return ElMessage.warning('请先勾选要删除的设备')
  const ids = [...store.allSelectedIds]
  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${ids.length} 台设备？真机模式下会一并销毁对应容器，此操作不可恢复。`,
      '批量删除',
      { type: 'warning', confirmButtonText: `删除 ${ids.length} 台`, cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  deleting.value = true
  try {
    const { data } = await api.batchDeleteDevices(ids)
    if (data.failed) {
      // 不能只说「已删除」——有删不掉的必须说清是哪几台、为什么
      ElMessage.warning(
        `删除 ${data.ok}/${data.total} 台；${data.failed} 台失败：` +
          data.details.map((x) => `#${x.device_id} ${x.error}`).join('；'),
      )
    } else {
      ElMessage.success(`已删除 ${data.ok} 台`)
    }
    // 清空已选（store + el-table 内部 reserve-selection）
    store.clearAllSelectedIds()
    selected.value = []
    tableRef.value?.clearSelection()
  } catch {
    return // 提示由 api/client.js 兜底
  } finally {
    deleting.value = false
  }
  await store.refresh({ q: filter.value.q || undefined, status: filter.value.status || undefined, group_id: filter.value.group_id || undefined })
  await store.refreshGroups()
}

async function remove(d) {
  await ElMessageBox.confirm(`删除设备「${d.name}」？`, '确认', { type: 'warning' })
  await act(api.deleteDevice, d.id, '已删除')
  // 若删除的是已选设备，从 store 里也移除（避免「已选 N/共 M」残留）
  if (store.allSelectedIds.includes(d.id)) {
    store.removeAllSelectedId(d.id)
    selected.value = selected.value.filter((x) => x.id !== d.id)
  }
}

async function newGroup() {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt('分组名称', '新建分组'))
  } catch {
    return // 用户取消
  }
  try {
    await api.createGroup({ name: value })
  } catch {
    return
  }
  await store.refreshGroups()
  ElMessage.success('分组已创建')
}

function showFp(d) {
  fpDevice.value = d
  fpDlg.value = true
}

const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }
const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }
</script>

<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-title">设备管理</div>
      <div class="page-header-right">
        <el-button @click="openSkinDlg">一键换肤</el-button>
        <el-button type="danger" :disabled="!store.allSelectedCount" :loading="deleting" @click="batchRemove">批量删除</el-button>
        <el-button type="primary" @click="createDlg = true">+ 添加设备</el-button>
      </div>
    </div>

    <!-- 筛选栏 + 已选统计 -->
    <div class="filter-bar">
      <el-input
        v-model="filter.q"
        placeholder="搜索设备名/IP/型号"
        clearable
        :prefix-icon="'Search'"
        style="width: 240px"
      />
      <el-select v-model="filter.status" placeholder="全部状态" clearable style="width: 140px">
        <el-option label="在线" value="running" />
        <el-option label="离线" value="stopped" />
        <el-option label="告警" value="error" />
        <el-option label="维护中" value="creating" />
      </el-select>
      <el-select v-model="filter.group_id" placeholder="全部分组" clearable style="width: 160px">
        <el-option v-for="g in store.groups" :key="g.id" :label="`${g.name} (${g.device_count})`" :value="g.id" />
      </el-select>
      <el-button size="small" link @click="newGroup">+ 新建分组</el-button>
      <div class="spacer"></div>
      <!-- 已选统计 + 全选所有页 + 清空选择 -->
      <el-tag :type="store.allSelectedCount ? 'success' : 'info'" effect="dark" class="selection-tag">
        已选 {{ store.allSelectedCount }} 台 / 共 {{ store.total }} 台
      </el-tag>
      <el-button size="small" type="primary" plain :loading="selectingAll" @click="selectAllPages">
        全选所有页
      </el-button>
      <el-button size="small" :disabled="!store.allSelectedCount" link @click="clearAllSelection">
        清空选择
      </el-button>
    </div>

    <!-- 设备表格 -->
    <el-table
      ref="tableRef"
      :data="store.list"
      stripe
      style="width: 100%"
      row-key="id"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="42" reserve-selection />
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="设备名" min-width="120" />
      <el-table-column label="型号" min-width="130">
        <template #default="{ row }">{{ row.fingerprint?.device?.model || '—' }}</template>
      </el-table-column>
      <el-table-column label="分组" width="140">
        <template #default="{ row }">
          <el-select
            :model-value="row.group_id"
            size="small"
            placeholder="—"
            clearable
            @change="(v) => assignGroup(row, v)"
          >
            <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <span class="status-cell">
            <span class="dot" :class="row.status"></span>
            {{ { running: '在线', stopped: '离线', creating: '维护中', error: '告警' }[row.status] || row.status }}
          </span>
          <el-tooltip v-if="row.last_error" placement="top" :show-after="150">
            <template #content>
              <div style="max-width: 460px; line-height: 1.8; white-space: pre-wrap">{{ row.last_error }}</div>
            </template>
            <el-icon color="#f56c6c" style="margin-left: 4px; vertical-align: -2px; cursor: help">
              <WarningFilled />
            </el-icon>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="IP" width="130">
        <template #default="{ row }">{{ row.fingerprint?.network?.exit_ip || '—' }}</template>
      </el-table-column>
      <el-table-column label="皮肤" width="110">
        <template #default="{ row }">
          <el-tag v-if="store.skinProgress[row.id]" size="small" :type="store.skinProgress[row.id].phase === 'failed' ? 'danger' : 'warning'" effect="plain">
            {{ SKIN_PHASE_TEXT[store.skinProgress[row.id].phase] || store.skinProgress[row.id].phase }}
          </el-tag>
          <span v-else-if="row.skin">{{ skinLabel(row.skin) }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="当前页面" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.current_url || ' — ' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="420" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="router.push(`/device/${row.id}`)">操控</el-button>
          <el-button size="small" link @click="router.push(`/detail/${row.id}`)">详情</el-button>
          <el-button size="small" link @click="showFp(row)">指纹</el-button>
          <el-dropdown size="small" trigger="click" @command="(theme) => applySkinRow(row.id, theme)">
            <el-button size="small" link style="margin-top: 5px;">换肤<el-icon style="margin-left: 2px"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="t in skinThemes" :key="t.key" :command="t.key">{{ t.label }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button
            size="small"
            link
            :type="row.status === 'running' ? 'warning' : ''"
            @click="act(row.status === 'running' ? api.stopDevice : api.startDevice, row.id, row.status === 'running' ? '已停止' : '已启动')"
          >{{ row.status === 'running' ? '停止' : '启动' }}</el-button>
          <el-button size="small" link @click="rename(row)">改名</el-button>
          <el-button size="small" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页：完整 layout（每页条数 + prev/pager/next + total） -->
    <div class="pagination-bar">
      <span class="page-info">
        显示第 {{ store.total ? (store.page - 1) * store.pageSize + 1 : 0 }}-{{ Math.min(store.page * store.pageSize, store.total) }} 条，共 {{ store.total }} 条
      </span>
      <el-pagination
        :current-page="store.page"
        :total="store.total"
        :page-size="store.pageSize"
        :page-sizes="[8, 20, 50, 100]"
        layout="sizes, prev, pager, next, total"
        size="small"
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </div>

    <!-- 批量建机 -->
    <el-dialog v-model="createDlg" title="批量创建云手机" width="440px" :close-on-click-modal="!creating" :show-close="!creating" :close-on-press-escape="!creating">
      <el-form label-width="92px">
        <el-form-item label="数量"><el-input-number v-model="form.count" :min="1" :max="50" /></el-form-item>
        <el-form-item label="名称前缀"><el-input v-model="form.name_prefix" /></el-form-item>
        <el-form-item label="分组">
          <el-select v-model="form.group_id" placeholder="不分组" clearable style="width: 100%">
            <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="分辨率">
          <el-select v-model="form.width" style="width: 110px">
            <el-option :value="720" label="720" />
            <el-option :value="1080" label="1080" />
          </el-select>
          <span style="margin: 0 6px">×</span>
          <el-select v-model="form.height" style="width: 110px">
            <el-option :value="1280" label="1280" />
            <el-option :value="1920" label="1920" />
          </el-select>
        </el-form-item>
        <el-form-item label="首页网址"><el-input v-model="form.target_url" placeholder="留空则显示 iOS 主屏" /></el-form-item>
        <el-form-item label="创建后启动"><el-switch v-model="form.auto_start" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="creating" @click="createDlg = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="batchCreate">开始创建</el-button>
      </template>
    </el-dialog>

    <!-- 一键换肤 -->
    <el-dialog v-model="skinDlg" title="一键换肤" width="460px">
      <el-form label-width="92px">
        <el-form-item label="皮肤主题">
          <el-radio-group v-model="skinForm.theme">
            <el-radio-button v-for="t in skinThemes" :key="t.key" :value="t.key">{{ t.label }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="应用范围">
          <el-radio-group v-model="skinForm.scope">
            <el-radio value="all">全部设备（{{ store.total }} 台）</el-radio>
            <el-radio value="selected" :disabled="!store.allSelectedCount">已选设备（{{ store.allSelectedCount }} 台）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="换肤两步生效：① 多画面预览/投屏即时切换主题（0 延迟）；② 真机后台逐台落地 —— 装 iOS 启动器(首次)→布置 4 列桌面/Dock→写入壁纸→重启生效，每台约 1–2 分钟，多台顺序进行；实时进度见列表「皮肤」列。"
        />
      </el-form>
      <template #footer>
        <el-button @click="skinDlg = false">取消</el-button>
        <el-button type="primary" :loading="skinning" @click="applySkinBatch">应用换肤</el-button>
      </template>
    </el-dialog>

    <!-- 指纹详情 -->
    <el-drawer v-model="fpDlg" :title="`一机一码 · ${fpDevice?.name}`" size="420px">
      <template v-if="fpDevice">
        <el-descriptions title="设备标识" :column="1" border size="small">
          <el-descriptions-item label="品牌/机型">{{ fpDevice.fingerprint.device.brand }} · {{ fpDevice.fingerprint.device.model }}</el-descriptions-item>
          <el-descriptions-item label="Android ID">{{ fpDevice.fingerprint.device.android_id }}</el-descriptions-item>
          <el-descriptions-item label="序列号">{{ fpDevice.fingerprint.device.serialno }}</el-descriptions-item>
          <el-descriptions-item label="IMEI">{{ fpDevice.fingerprint.device.imei }}</el-descriptions-item>
          <el-descriptions-item label="MAC">{{ fpDevice.fingerprint.device.mac }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions title="浏览器指纹" :column="1" border size="small" style="margin-top: 14px">
          <el-descriptions-item label="UA">{{ fpDevice.fingerprint.browser.user_agent }}</el-descriptions-item>
          <el-descriptions-item label="时区/语言">{{ fpDevice.fingerprint.browser.timezone }} / {{ fpDevice.fingerprint.browser.language }}</el-descriptions-item>
          <el-descriptions-item label="WebGL">{{ fpDevice.fingerprint.browser.webgl_renderer }}</el-descriptions-item>
          <el-descriptions-item label="Canvas 噪声">{{ fpDevice.fingerprint.browser.canvas_noise_seed }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions title="网络" :column="1" border size="small" style="margin-top: 14px">
          <el-descriptions-item label="出口 IP">{{ fpDevice.fingerprint.network.exit_ip }}</el-descriptions-item>
          <el-descriptions-item label="代理">{{ fpDevice.fingerprint.network.proxy || '直连' }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.spacer {
  flex: 1;
}
.selection-tag {
  font-weight: 600;
}
.device-count {
  color: var(--text-secondary);
  font-size: 14px;
  white-space: nowrap;
}
.status-cell {
  display: inline-flex;
  align-items: center;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
}
.page-info {
  color: var(--text-secondary);
  font-size: 13px;
}
:deep(.el-table) {
  border-radius: var(--radius-sm);
  overflow: hidden;
}
</style>
