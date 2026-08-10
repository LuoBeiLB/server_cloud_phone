<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { api } from '../api/client'

// 分组树（多级 ≤3 级）
const tree = ref([])
const ungrouped = ref(0)
const maxDepth = ref(3)
const treeLoading = ref(false)

// 设备
const devices = ref([])
const devLoading = ref(false)
const selectedRows = ref([])
const targetGroupId = ref(null)

// 当前选中的分组（点击树节点）
const selectedGroup = ref(null) // { id, name } | null
const deviceFilter = ref('all') // all | selected | ungrouped

const treeProps = { children: 'children', label: 'name' }

const statusType = { running: 'success', stopped: 'info', creating: 'warning', error: 'danger' }
const statusText = { running: '运行中', stopped: '已停止', creating: '创建中', error: '异常' }

// ---------- 数据加载 ----------
async function loadTree() {
  treeLoading.value = true
  try {
    const { data } = await http.get('/groups/tree')
    tree.value = data.roots || []
    ungrouped.value = data.ungrouped_count || 0
    maxDepth.value = data.max_depth || 3
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载分组树失败')
  } finally {
    treeLoading.value = false
  }
}

async function loadDevices() {
  devLoading.value = true
  try {
    const { data } = await api.listDevices()
    devices.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载设备失败')
  } finally {
    devLoading.value = false
  }
}

async function reloadAll() {
  await Promise.all([loadTree(), loadDevices()])
}

onMounted(reloadAll)

// ---------- 扁平化：用于「目标分组」下拉，带层级缩进 ----------
function flatten(nodes, depth = 0, acc = []) {
  for (const n of nodes) {
    acc.push({ id: n.id, label: '　'.repeat(depth) + n.name, count: n.device_count })
    if (n.children && n.children.length) flatten(n.children, depth + 1, acc)
  }
  return acc
}
const groupOptions = computed(() => flatten(tree.value))
const nameById = computed(() => {
  const m = {}
  const walk = (nodes) => nodes.forEach((n) => {
    m[n.id] = n.name
    if (n.children) walk(n.children)
  })
  walk(tree.value)
  return m
})
function groupName(id) {
  return id == null ? '未分组' : nameById.value[id] || `#${id}`
}

// ---------- 设备过滤 ----------
const filteredDevices = computed(() => {
  if (deviceFilter.value === 'ungrouped') return devices.value.filter((d) => d.group_id == null)
  if (deviceFilter.value === 'selected' && selectedGroup.value)
    return devices.value.filter((d) => d.group_id === selectedGroup.value.id)
  return devices.value
})

function onNodeClick(data) {
  selectedGroup.value = { id: data.id, name: data.name }
  deviceFilter.value = 'selected'
}

// ---------- 分组增删改 ----------
async function createGroup(parentId, parentName) {
  try {
    const { value } = await ElMessageBox.prompt(
      parentId ? `在「${parentName}」下新建子分组` : '新建顶级分组',
      parentId ? '新建子分组' : '新建顶级分组',
      { inputValidator: (v) => (v && v.trim() ? true : '请输入分组名称'), confirmButtonText: '确定', cancelButtonText: '取消' },
    )
    await http.post('/groups', { name: value.trim(), parent_id: parentId ?? null })
    ElMessage.success('分组已创建')
    await loadTree()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

async function renameNode(data) {
  try {
    const { value } = await ElMessageBox.prompt('新名称', '重命名分组', {
      inputValue: data.name,
      inputValidator: (v) => (v && v.trim() ? true : '请输入分组名称'),
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
    await http.patch(`/groups/${data.id}`, { name: value.trim() })
    ElMessage.success('已重命名')
    await loadTree()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '重命名失败')
  }
}

async function removeNode(data) {
  try {
    await ElMessageBox.confirm(
      `删除分组「${data.name}」？其下设备将变为未分组，子分组将上提为顶级。`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await api.deleteGroup(data.id)
    ElMessage.success('已删除')
    if (selectedGroup.value?.id === data.id) {
      selectedGroup.value = null
      deviceFilter.value = 'all'
    }
    await reloadAll()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// ---------- 拖拽移动分组（re-parent，后端校验层级/环） ----------
function allowDrop(draggingNode, dropNode, type) {
  // 不允许把节点拖成自身子级；其余交给后端 PATCH 校验
  return !(type === 'inner' && draggingNode.data.id === dropNode.data.id)
}

async function onNodeDrop(draggingNode, dropNode, dropType) {
  const id = draggingNode.data.id
  let parentId = null
  if (dropType === 'inner') parentId = dropNode.data.id
  else parentId = dropNode.data.parent_id ?? null
  try {
    await http.patch(`/groups/${id}`, { parent_id: parentId })
    ElMessage.success('分组已移动')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '移动失败')
  } finally {
    await loadTree() // 以服务端为准，重建树（失败时回滚视图）
  }
}

// ---------- 设备移动 ----------
function onSelectionChange(rows) {
  selectedRows.value = rows
}

async function moveDevices(gid) {
  const ids = selectedRows.value.map((r) => r.id)
  if (!ids.length) {
    ElMessage.warning('请先勾选设备')
    return
  }
  try {
    const { data } = await http.post(`/groups/${gid ?? 0}/move-devices`, { device_ids: ids })
    ElMessage.success(`已移动 ${data.moved} 台设备`)
    selectedRows.value = []
    await reloadAll()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '移动失败')
  }
}
</script>

<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-title">分组管理</div>
      <div class="page-header-right">
        <el-button type="primary" @click="createGroup(null)">+ 新建分组</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左栏：分组列表 -->
      <el-col :span="9">
        <el-card shadow="never" class="panel-card">
          <div class="panel-header">
            <span class="panel-title">分组列表</span>
            <span class="panel-count">{{ groupOptions.length }}个分组</span>
          </div>

          <el-tree
            :data="tree"
            :props="treeProps"
            node-key="id"
            draggable
            :allow-drop="allowDrop"
            @node-drop="onNodeDrop"
            @node-click="onNodeClick"
            v-loading="treeLoading"
            class="group-tree"
          >
            <template #default="{ data }">
              <div class="group-list-item" :class="{ active: selectedGroup?.id === data.id }">
                <span class="group-item-name">{{ data.name }}</span>
                <span class="group-item-actions">
                  <span class="group-item-count">{{ data.device_count }}</span>
                  <el-button size="small" link @click.stop="renameNode(data)">改名</el-button>
                  <el-button size="small" link type="danger" @click.stop="removeNode(data)">删除</el-button>
                </span>
              </div>
            </template>
          </el-tree>
          <el-empty v-if="!treeLoading && !tree.length" description="暂无分组" :image-size="60" />

          <div class="group-list-footer">
            <span>未分组设备</span>
            <strong>{{ ungrouped }}</strong>
          </div>
          <div class="group-list-footer">
            <span>设备总数</span>
            <strong>{{ devices.length }}</strong>
          </div>
        </el-card>
      </el-col>

      <!-- 右栏：移动设备到分组 -->
      <el-col :span="15">
        <el-card shadow="never" class="panel-card">
          <div class="panel-header">
            <span class="panel-title">移动设备到分组</span>
          </div>

          <div class="move-form">
            <div class="form-row">
              <label class="form-label">源分组</label>
              <el-select
                :model-value="selectedGroup?.id ?? null"
                placeholder="选择源分组（留空=全部）"
                clearable
                style="width: 100%"
                @change="(id) => {
                  if (id) {
                    selectedGroup = { id, name: groupOptions.find(g => g.id === id)?.label?.replace(/　/g, '')?.trim() || '' }
                    deviceFilter = 'selected'
                  } else {
                    selectedGroup = null
                    deviceFilter = 'all'
                  }
                }"
              >
                <el-option v-for="g in groupOptions" :key="g.id" :label="g.label.replace(/　/g, '').trim()" :value="g.id" />
              </el-select>
            </div>
            <div class="form-row">
              <label class="form-label">目标分组</label>
              <el-select
                v-model="targetGroupId"
                placeholder="选择目标分组"
                clearable
                style="width: 100%"
              >
                <el-option v-for="g in groupOptions" :key="g.id" :label="g.label.replace(/　/g, '').trim()" :value="g.id" />
              </el-select>
            </div>
          </div>

          <el-table
            :data="filteredDevices"
            v-loading="devLoading"
            border
            stripe
            size="small"
            height="calc(100vh - 380px)"
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" width="44" />
            <el-table-column prop="name" label="设备名" min-width="120" />
            <el-table-column label="型号" min-width="120">
              <template #default="{ row }">{{ row.fingerprint?.device?.model || '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <span class="dot" :class="row.status"></span>
                {{ { running: '在线', stopped: '离线', creating: '维护中', error: '告警' }[row.status] || row.status }}
              </template>
            </el-table-column>
            <el-table-column label="当前分组" min-width="120">
              <template #default="{ row }">
                <el-tag v-if="row.group_id != null" size="small" effect="plain">{{ groupName(row.group_id) }}</el-tag>
                <span v-else class="muted">未分组</span>
              </template>
            </el-table-column>
          </el-table>

          <div class="move-footer">
            <span class="selected-count">已选择 {{ selectedRows.length }} 台设备</span>
            <div class="spacer"></div>
            <el-button
              type="primary"
              :disabled="!selectedRows.length || targetGroupId == null"
              @click="moveDevices(targetGroupId)"
            >✓ 确认移动</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.panel-card {
  border: 1px solid var(--card-border);
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}
.panel-count {
  font-size: 13px;
  color: var(--text-muted);
}
.group-tree {
  max-height: calc(100vh - 340px);
  overflow-y: auto;
}
:deep(.group-tree .el-tree-node__content) {
  height: auto;
  padding: 2px 0;
}
.group-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all .15s;
  margin-bottom: 4px;
  width: 100%;
}
.group-list-item:hover {
  background: var(--brand-bg);
}
.group-list-item.active {
  background: var(--brand-bg);
  color: var(--brand-dark);
  font-weight: 600;
}
.group-item-name {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
}
.group-item-count {
  background: #f1f5f9;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 10px;
}
.group-list-item.active .group-item-count {
  background: var(--brand);
  color: #fff;
}
.group-list-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0 0;
  margin-top: 8px;
  border-top: 1px solid var(--card-border);
  font-size: 14px;
  color: var(--text-secondary);
}
.group-list-footer strong {
  color: var(--brand);
  font-size: 18px;
}
.move-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.move-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--card-border);
}
.selected-count {
  font-size: 14px;
  color: var(--text-secondary);
}
.muted {
  color: var(--text-muted);
}
.spacer {
  flex: 1;
}
.group-item-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
