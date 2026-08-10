<script setup>
import { onMounted, ref, computed } from 'vue'
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

const filtered = computed(() =>
  store.list.filter((d) => {
    if (filter.value.status && d.status !== filter.value.status) return false
    if (filter.value.group_id && d.group_id !== filter.value.group_id) return false
    if (filter.value.q && !d.name.includes(filter.value.q)) return false
    return true
  }),
)

onMounted(async () => {
  store.refresh()
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
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '换肤失败')
  }
}

async function applySkinBatch() {
  skinning.value = true
  try {
    const ids = skinForm.value.scope === 'filtered' ? filtered.value.map((d) => d.id) : []
    const r = await api.applySkinBatch(ids, skinForm.value.theme)
    ElMessage.success(
      `已为 ${r.data.count} 台设备换肤：${skinLabel(skinForm.value.theme)} · 真机逐台落地中，进度见「皮肤」列`,
    )
    skinDlg.value = false
    await store.refresh()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '换肤失败')
  } finally {
    skinning.value = false
  }
}

async function batchCreate() {
  creating.value = true
  try {
    await api.batchCreate(form.value)
    ElMessage.success(`已创建 ${form.value.count} 台云手机`)
    createDlg.value = false
    await store.refresh()
    await store.refreshGroups()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function act(fn, id, okMsg) {
  try {
    await fn(id)
    if (okMsg) ElMessage.success(okMsg)
    await store.refresh()
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
  await store.refresh()
  ElMessage.success('已重命名')
}

async function assignGroup(d, gid) {
  try {
    await api.updateDevice(d.id, { group_id: gid })
  } catch {
    await store.refresh() // 回滚界面上的乐观显示，避免看起来改成功了
    return
  }
  await store.refresh()
  await store.refreshGroups()
}

// ---- 批量删除 ----
// 切后端 / 跑过冒烟测试后常留下几十台废设备，一台台点删除不可接受。
const selected = ref([])
const deleting = ref(false)
function onSelectionChange(rows) {
  selected.value = rows
}
async function batchRemove() {
  const ids = selected.value.map((d) => d.id)
  if (!ids.length) return ElMessage.warning('请先勾选要删除的设备')
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
    selected.value = []
  } catch {
    return // 提示由 api/client.js 兜底
  } finally {
    deleting.value = false
  }
  await store.refresh()
  await store.refreshGroups()
}

async function remove(d) {
  await ElMessageBox.confirm(`删除设备「${d.name}」？`, '确认', { type: 'warning' })
  await act(api.deleteDevice, d.id, '已删除')
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
    <div class="toolbar">
      <el-button type="primary" :icon="'Plus'" @click="createDlg = true">批量建机</el-button>
      <el-button :icon="'FolderAdd'" @click="newGroup">新建分组</el-button>
      <el-button :icon="'MagicStick'" @click="skinDlg = true">一键换肤</el-button>
      <el-button
        type="danger"
        plain
        :icon="'Delete'"
        :disabled="!selected.length"
        :loading="deleting"
        @click="batchRemove"
      >批量删除{{ selected.length ? ` (${selected.length})` : '' }}</el-button>
      <el-divider direction="vertical" />
      <el-input v-model="filter.q" placeholder="搜索名称" style="width: 160px" clearable :prefix-icon="'Search'" />
      <el-select v-model="filter.status" placeholder="状态" clearable style="width: 120px">
        <el-option label="运行中" value="running" />
        <el-option label="已停止" value="stopped" />
        <el-option label="异常" value="error" />
      </el-select>
      <el-select v-model="filter.group_id" placeholder="分组" clearable style="width: 140px">
        <el-option v-for="g in store.groups" :key="g.id" :label="`${g.name} (${g.device_count})`" :value="g.id" />
      </el-select>
      <div class="spacer"></div>
      <el-button :icon="'Refresh'" @click="store.refresh()">刷新</el-button>
    </div>

    <el-table
      :data="filtered"
      border
      stripe
      style="width: 100%"
      size="small"
      row-key="id"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="42" reserve-selection />
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="名称" width="140" />
      <el-table-column label="状态" width="112">
        <template #default="{ row }">
          <el-tag :type="statusType[row.status]" size="small">{{ statusText[row.status] }}</el-tag>
          <!-- 拉起/启动失败的原因必须在列表里就能看到。
               只显示「异常」而把原因藏在后端日志里，等于没有提示。
               last_error 由后端写入，内容是「原因 ｜ 处置 ｜ 证据」。 -->
          <el-tooltip v-if="row.last_error" placement="top" :show-after="150">
            <template #content>
              <div style="max-width: 460px; line-height: 1.8; white-space: pre-wrap">{{
                row.last_error
              }}</div>
            </template>
            <el-icon color="#f56c6c" style="margin-left: 5px; vertical-align: -2px; cursor: help">
              <WarningFilled />
            </el-icon>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="机型" width="150">
        <template #default="{ row }">{{ row.fingerprint?.device?.model }}</template>
      </el-table-column>
      <el-table-column label="出口 IP" width="130">
        <template #default="{ row }">{{ row.fingerprint?.network?.exit_ip }}</template>
      </el-table-column>
      <el-table-column label="皮肤" width="150">
        <template #default="{ row }">
          <template v-if="store.skinProgress[row.id]">
            <el-tag
              size="small"
              :type="{ done: 'success', failed: 'danger' }[store.skinProgress[row.id].phase] || 'warning'"
            >
              <el-icon
                v-if="!['done', 'failed'].includes(store.skinProgress[row.id].phase)"
                class="is-loading"
                style="vertical-align: -2px; margin-right: 3px"
              ><Loading /></el-icon>
              {{ SKIN_PHASE_TEXT[store.skinProgress[row.id].phase] || store.skinProgress[row.id].phase }}
            </el-tag>
          </template>
          <el-tag v-else-if="row.skin" size="small" effect="plain" type="warning">{{ skinLabel(row.skin) }}</el-tag>
          <!-- 空 = 还没换过肤，显示原生，别谎报成「iOS 风」 -->
          <el-tag v-else size="small" effect="plain" type="info">原生安卓</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="当前页面" min-width="180">
        <template #default="{ row }">
          <span style="color: #007aff">{{ row.current_url || '主屏（iOS 皮肤）' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="分组" width="130">
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
      <el-table-column label="操作" width="410" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/device/${row.id}`)">操控</el-button>
          <el-button size="small" @click="router.push(`/detail/${row.id}`)">详情</el-button>
          <el-button size="small" @click="showFp(row)">指纹</el-button>
          <el-dropdown size="small" trigger="click" style="margin: 0 8px" @command="(t) => applySkinRow(row.id, t)">
            <el-button size="small" type="warning" plain>
              换肤<el-icon style="margin-left: 2px"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <!-- 当前主题不禁用：允许「重新落地」（新建机默认 ios 但真机未落地时用得上） -->
                <el-dropdown-item
                  v-for="t in skinThemes"
                  :key="t.key"
                  :command="t.key"
                >{{ t.label }}{{ (row.skin || 'ios') === t.key ? ' ✓' : '' }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button
            v-if="row.status !== 'running'"
            size="small"
            type="success"
            @click="act(api.startDevice, row.id, '已启动')"
            >启动</el-button
          >
          <el-button v-else size="small" type="warning" @click="act(api.stopDevice, row.id, '已停止')"
            >停止</el-button
          >
          <el-button size="small" @click="rename(row)">改名</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 批量建机 -->
    <el-dialog v-model="createDlg" title="批量创建云手机" width="440px">
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
        <el-button @click="createDlg = false">取消</el-button>
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
            <el-radio value="all">全部设备（{{ store.list.length }} 台）</el-radio>
            <el-radio value="filtered">当前筛选结果（{{ filtered.length }} 台）</el-radio>
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
