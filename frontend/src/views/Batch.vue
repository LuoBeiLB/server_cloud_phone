<script setup>
// 批量操控台
//
// 核心交互（v7：显式两步——先选主控，再勾从机）：
//   1) 进入页面：store.refresh({ page_size: 100 }) 拉全设备列表 + 一次性拉 50 张静态预览
//   2) 顶部「主控设备」下拉：单选，决定主控画板跟谁
//   3) 顶部「全选 / 清空」按钮：批量管理从机池
//   4) 底部多画面预览：默认全设备都在 N×N 网格（4×4，可调 1~8），不依赖设备管理页的勾选
//      - PhoneFrame selectable=true，右上角有勾选框
//      - 勾选 = 加入从机池（外层绿色描边 + 左上"从"徽标）
//      - 取消勾选 = 移出从机池
//      - 主控那台额外加蓝色描边 + 左上"主"徽标
//   5) 主控画板：复用 PhoneFrame（与 SingleView 一致），点击/滑动/快捷键 → 归一到
//      1080×1920 → /batch/tap /batch/swipe /batch/key 同步下发到从机池
//   6) 3 张 side-card：一键批量开网页 / 批量输入 / 批量装 APK（用从机池）
//
// 设计取舍：
//   - 进入页面默认：主控 = store.list 第 1 台，从机池 = 空。强制用户先选主控再勾从机。
//   - 从机池用 store.allSelectedIds 存（跨页面共享，刷新不丢）。
//   - 主控画板用 <PhoneFrame clickable swipeable>：与 SingleView 共用同一份手势/坐标/轨迹/描边。
//   - PhoneFrame @tap / @swipe 给的是主控真实分辨率坐标，批量接口用 1080×1920 归一，
//     所以拿到坐标后折算到 0~1 再 × 1080×1920 下发。设备分辨率变化不影响坐标正确性。
//   - 快捷键映射：home/back/recents/volume_up/volume_down/power
import { onMounted, onBeforeUnmount, ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled, HomeFilled, Back, Refresh, Top, Bottom, Phone, Connection } from '@element-plus/icons-vue'
import { api } from '../api/client'
import { useDevices } from '../stores/devices'
import PhoneFrame from '../components/PhoneFrame.vue'

const store = useDevices()

// ---------------- 顶部状态：主控 + 从机池 + 总览 ----------------
const masterId = ref(null)
const masterFrame = ref('')
const lastAction = ref('')

const allDevices = computed(() => store.list)
const totalCount = computed(() => allDevices.value.length)
// 服务端设备总数（分页接口返回；页面只加载前 100 台时它才是真实总数）
const totalDeviceCount = computed(() => store.total || totalCount.value)
// 是否已全选：从机数 ≥ 总数-主控1台
const isAllSlaves = computed(() => slaveCount.value > 0 && slaveCount.value >= totalDeviceCount.value - 1)
// 从机池 = store.allSelectedIds 中排除主控的那台
const slaveIds = computed(() => store.allSelectedIds.filter((id) => id !== masterId.value))
const slaveCount = computed(() => slaveIds.value.length)
const masterDevice = computed(() => allDevices.value.find((d) => d.id === masterId.value) || null)

// 多画面预览：底部 N×N 网格（默认 4×4，可调 1~8）
const gridN = ref(4)
const gridOptions = Array.from({ length: 8 }, (_, i) => i + 1)

// 多画面预览显示的设备 = store.list 全量（不依赖设备管理勾选）
const previewDevices = computed(() => [...allDevices.value].sort((a, b) => a.id - b.id))

// ---------------- 设备状态判定 ----------------
function isMaster(id) {
  return id === masterId.value
}
function isSlave(id) {
  return id !== masterId.value && store.allSelectedIds.includes(id)
}
function cellRole(id) {
  if (isMaster(id)) return 'role-master'
  if (isSlave(id)) return 'role-slave'
  return ''
}

// ---------------- 主控：顶部下拉切换 ----------------
function onMasterChange(newId) {
  if (newId == null) return
  masterId.value = newId
  masterFrame.value = ''
  lastAction.value = ''
  ElMessage.success(`主控已切换为 #${newId}`)
}

// ---------------- 从机：勾选框切换 + 全选/清空 ----------------
function toggleSlave(id) {
  if (id === masterId.value) {
    ElMessage.info('主控设备无需勾选')
    return
  }
  if (store.allSelectedIds.includes(id)) {
    store.removeAllSelectedId(id)
  } else {
    store.addAllSelectedId(id)
  }
}

// 全选所有从机：按服务端总数分页拉全部 id（页面列表只加载前 100 台，不能只选已加载的）
const selectingAll = ref(false)
async function selectAllSlaves() {
  if (!totalDeviceCount.value) return
  selectingAll.value = true
  try {
    const ids = []
    const pageSize = 100
    let p = 1
    while (ids.length < totalDeviceCount.value) {
      const { data } = await api.listDevices({ page: p, page_size: pageSize })
      const items = Array.isArray(data) ? data : data.items || []
      if (items.length === 0) break
      ids.push(...items.map((d) => d.id))
      if (items.length < pageSize) break
      p += 1
      if (p > 50) break // 保险：最多 5000 台，防后端 total 不准导致死循环
    }
    store.setAllSelectedIds(ids)
    // 主控自动加进从机池，避免"全选"后主控被排除
    if (masterId.value && !ids.includes(masterId.value)) {
      store.addAllSelectedId(masterId.value)
    }
    ElMessage.success(`已加入 ${slaveIds.value.length} 台从机`)
  } catch (e) {
    ElMessage.error(e?.friendly || '全选失败')
  } finally {
    selectingAll.value = false
  }
}

function clearAllSlaves() {
  store.clearAllSelectedIds()
  // 主控不能取消（清空后保留主控）
  if (masterId.value) store.addAllSelectedId(masterId.value)
  ElMessage.success('已清空从机池')
}

// ---------------- 进入页面：拉全设备 + 一次性拉全 50 张静态预览 ----------------
async function loadAllDeviceSnapshots() {
  if (!allDevices.value.length) return
  const results = await Promise.allSettled(
    allDevices.value.map(async (d) => {
      try {
        const { data } = await api.screenshot(d.id)
        return { id: d.id, frame: data?.frame, action: data?.last_action }
      } catch {
        return { id: d.id, frame: null }
      }
    }),
  )
  for (const r of results) {
    if (r.status === 'fulfilled' && r.value?.frame) {
      store.frames[r.value.id] = r.value.frame
      if (r.value.action) store.lastActions[r.value.id] = r.value.action
    }
  }
}

// ---------------- 主控投屏（ws-scrcpy H.264 直连，可直接操控） ----------------
// 与 Control.vue 内嵌投屏同一条链路：/api/health → ws_scrcpy_base + adb_port 拼 URL。
// 未部署 / 主控无 adb 端口时按钮禁用，退回截图模式。
const wsScrcpyBase = ref('')
const scrcpyDisabled = computed(() => !wsScrcpyBase.value || !masterDevice.value?.adb_port)
const scrcpyUrl = computed(() => {
  if (scrcpyDisabled.value) return ''
  const udid = `localhost:${masterDevice.value.adb_port}`
  const base = wsScrcpyBase.value.replace(/\/+$/, '')
  const wsProto = base.startsWith('https') ? 'wss' : 'ws'
  const innerWs =
    `${wsProto}://${base.replace(/^https?:\/\//, '')}` +
    `/?action=proxy-adb&remote=tcp:8886&udid=${encodeURIComponent(udid)}`
  return (
    `${base}/#!action=stream&udid=${encodeURIComponent(udid)}` +
    `&player=broadway&ws=${encodeURIComponent(innerWs)}`
  )
})

// 主控画板默认本地截图模式（2s 轮询，稳定可控）；投屏为手动切换：
// ws-scrcpy 服务可用时点「投屏模式」进 H.264 直连 iframe，再点「退出投屏」回来。
// 注意：投屏中的点按/滑动由 ws-scrcpy 直连主控（不经后端），同时经 follow 补丁
// postMessage 广播到从机池（需 ws-scrcpy dist 打了 follow 补丁；未打时仅主控动）。
// 虚拟按键和三张 side-card 的批量操作不受影响（仍广播主控+从机全池）。
const embedStream = ref(false)
function toggleEmbed() {
  if (scrcpyDisabled.value) {
    return ElMessage.warning(
      !wsScrcpyBase.value
        ? '未部署 ws-scrcpy 投屏服务（后端设 CLOUD_WS_SCRCPY_BASE=http://<地址>:8100 启用）'
        : '主控设备无 adb 端口，不支持投屏',
    )
  }
  embedStream.value = !embedStream.value
  if (embedStream.value) {
    stopMasterPolling()
  } else {
    startMasterPolling()
  }
}

// ---------------- 主控轮询：2s/帧强制 HTTP（保证点击实时反馈） ----------------
let masterTimer = null
let masterBusy = false
const POLL_INTERVAL_MS = 2000

async function pollMaster() {
  if (masterBusy || !masterId.value) return
  masterBusy = true
  try {
    const { data } = await api.screenshot(masterId.value)
    if (data?.frame) {
      masterFrame.value = data.frame
      store.frames[masterId.value] = data.frame
      if (data.last_action) lastAction.value = data.last_action
    }
  } catch {
    /* 单帧失败不打断轮询 */
  } finally {
    masterBusy = false
  }
}

function startMasterPolling() {
  stopMasterPolling()
  if (!masterId.value) return
  pollMaster()
  masterTimer = setInterval(pollMaster, POLL_INTERVAL_MS)
}
function stopMasterPolling() {
  if (masterTimer) {
    clearInterval(masterTimer)
    masterTimer = null
  }
}

// ---------------- 从机池轮询：1.5s/帧并发拉 ----------------
const slaveFrames = ref({})
const SLAVE_POLL_MS = 1500
let slaveTimer = null
let slaveBusy = false

async function pollSlaves() {
  if (slaveBusy) return
  const ids = broadcastTargets()
  if (!ids.length) {
    slaveFrames.value = {}
    return
  }
  slaveBusy = true
  try {
    const results = await Promise.allSettled(
      ids.map(async (id) => {
        const { data } = await api.screenshot(id)
        return { id, frame: data?.frame, action: data?.last_action }
      }),
    )
    const next = { ...slaveFrames.value }
    for (const r of results) {
      if (r.status === 'fulfilled' && r.value?.frame) {
        next[r.value.id] = r.value.frame
        if (r.value.action) store.lastActions[r.value.id] = r.value.action
      }
    }
    slaveFrames.value = next
  } catch {
    /* 单台失败由下次轮询兜底 */
  } finally {
    slaveBusy = false
  }
}

function startSlavePolling() {
  stopSlavePolling()
  if (!slaveIds.value.length) {
    slaveFrames.value = {}
    return
  }
  pollSlaves()
  slaveTimer = setInterval(pollSlaves, SLAVE_POLL_MS)
}
function stopSlavePolling() {
  if (slaveTimer) {
    clearInterval(slaveTimer)
    slaveTimer = null
  }
}

watch(masterId, () => {
  // 主控变化时同步从机池（主控自动加入 allSelectedIds 避免被踢出）
  if (masterId.value && !store.allSelectedIds.includes(masterId.value)) {
    store.addAllSelectedId(masterId.value)
  }
  slaveFrames.value = {}
  startSlavePolling()
  if (embedStream.value) {
    stopMasterPolling() // 投屏中：iframe src 已跟随主控切换，不拉截图
  } else {
    startMasterPolling()
  }
})

watch(
  () => store.allSelectedIds.length,
  () => {
    startSlavePolling()
  },
)

// ---------------- 主控画板：复用 PhoneFrame（与 SingleView 体验一致） ----------------
const REF_W = 1080
const REF_H = 1920

// 主控真实坐标 → 1080×1920 归一坐标
function toRefFromDevice(x, y) {
  const W = masterDevice.value?.width
  const H = masterDevice.value?.height
  if (!W || !H) return { x: 0, y: 0 }
  return {
    x: Math.round((x / W) * REF_W),
    y: Math.round((y / H) * REF_H),
  }
}

// 广播目标 = 主控 + 从机池：主控画板上的操作主控自己也要执行，
// 否则盯着主控画面操作看起来「没反应」（v7 只发从机的坑）。
function broadcastTargets() {
  return [masterId.value, ...slaveIds.value].filter(Boolean)
}

const broadcasting = ref(false)
async function broadcastTap(x, y) {
  const ids = broadcastTargets()
  if (!ids.length) return ElMessage.warning('请先勾选从机（底部多画面预览里勾选，或点顶部「全选」）')
  if (!masterId.value) return ElMessage.warning('请先选主控')
  broadcasting.value = true
  try {
    const { data } = await api.batchTap(ids, x, y)
    lastAction.value = `点击 (${x},${y}) · 同步 ${data?.ok ?? 0}/${data?.total ?? ids.length}`
    ElMessage.success(`点击 (${x},${y}) · 同步 ${data?.ok ?? ids.length} 台`)
  } catch (e) {
    ElMessage.error(e?.friendly || '点击下发失败')
  } finally {
    broadcasting.value = false
  }
}

async function broadcastSwipe(x1, y1, x2, y2, durationMs = 300) {
  const ids = broadcastTargets()
  if (!ids.length) return ElMessage.warning('请先勾选从机（底部多画面预览里勾选，或点顶部「全选」）')
  if (!masterId.value) return ElMessage.warning('请先选主控')
  broadcasting.value = true
  try {
    const { data } = await api.batchSwipe(ids, x1, y1, x2, y2, durationMs)
    lastAction.value = `滑动 (${x1},${y1})→(${x2},${y2}) · 同步 ${data?.ok ?? 0}/${data?.total ?? ids.length}`
    ElMessage.success(`滑动 (${x1},${y1})→(${x2},${y2}) · 同步 ${data?.ok ?? ids.length} 台`)
  } catch (e) {
    ElMessage.error(e?.friendly || '滑动下发失败')
  } finally {
    broadcasting.value = false
  }
}

// PhoneFrame @tap / @swipe 事件 → 归一到 1080×1920 → 批量下发
// 跟 SingleView 一样的阈值：< 4% 短边算 tap，否则算 swipe（80~1500ms）
// ---------------- 投屏跟随：iframe 内点按/滑动 → 广播从机池 ----------------
// 依赖 ws-scrcpy dist 的 follow 事件补丁（setup-ws-scrcpy.sh v3 注入 index.html）：
// iframe 旁听 pointer 事件，postMessage({type:'cp-scrcpy-follow', kind:'tap'|'swipe',
// 坐标为相对画面的 0~1 归一值})。主控已由 ws-scrcpy 直连执行，这里只发从机避免重复；
// 归一值直接乘 REF 基准（与 toRefFromDevice 线性等价）。
let followBusy = false
function onFollowMessage(e) {
  const d = e?.data
  if (!d || d.type !== 'cp-scrcpy-follow' || !embedStream.value) return
  const ids = [...slaveIds.value]
  if (!ids.length || followBusy) return
  followBusy = true
  ;(async () => {
    try {
      let data
      if (d.kind === 'swipe') {
        const x1 = Math.round((d.x1 || 0) * REF_W)
        const y1 = Math.round((d.y1 || 0) * REF_H)
        const x2 = Math.round((d.x2 || 0) * REF_W)
        const y2 = Math.round((d.y2 || 0) * REF_H)
        ;({ data } = await api.batchSwipe(ids, x1, y1, x2, y2, d.dur || 300))
        lastAction.value = `投屏滑动 (${x1},${y1})→(${x2},${y2}) · 从机 ${data?.ok ?? 0}/${data?.total ?? ids.length}`
      } else {
        const x = Math.round((d.x || 0) * REF_W)
        const y = Math.round((d.y || 0) * REF_H)
        ;({ data } = await api.batchTap(ids, x, y))
        lastAction.value = `投屏点击 (${x},${y}) · 从机 ${data?.ok ?? 0}/${data?.total ?? ids.length}`
      }
    } catch (err) {
      ElMessage.error(err?.friendly || '投屏跟随下发失败')
    } finally {
      followBusy = false
    }
  })()
}

function onMasterTap(pt) {
  if (!masterId.value) return
  const { x, y } = toRefFromDevice(pt.x, pt.y)
  broadcastTap(x, y)
}
function onMasterSwipe(p) {
  if (!masterId.value) return
  const a = toRefFromDevice(p.x1, p.y1)
  const b = toRefFromDevice(p.x2, p.y2)
  broadcastSwipe(a.x, a.y, b.x, b.y, p.duration_ms)
}

// ---------------- 快捷键 ----------------
const KEY_MAP = [
  { key: 'home', label: 'Home', icon: HomeFilled },
  { key: 'back', label: '返回', icon: Back },
  { key: 'recents', label: '最近', icon: Refresh },
  { key: 'volume_up', label: '音量+', icon: Top },
  { key: 'volume_down', label: '音量-', icon: Bottom },
  { key: 'power', label: '电源', icon: Phone },
]

async function broadcastKey(k) {
  const ids = broadcastTargets()
  if (!ids.length) return ElMessage.warning('请先勾选从机（底部多画面预览里勾选，或点顶部「全选」）')
  if (!masterId.value) return ElMessage.warning('请先选主控')
  broadcasting.value = true
  try {
    const { data } = await api.batchKey(ids, k)
    lastAction.value = `按键 ${k} · 同步 ${data?.ok ?? 0}/${data?.total ?? ids.length}`
    ElMessage.success(`按键 ${k} · 同步 ${data?.ok ?? ids.length} 台`)
  } catch (e) {
    ElMessage.error(e?.friendly || '按键下发失败')
  } finally {
    broadcasting.value = false
  }
}

// ---------------- 3 张 side-card ----------------
const batchUrl = ref('https://www.baidu.com')
const batchText = ref('Hello World')
const batchApk = ref('https://example.com/app.apk')

function needSlaves() {
  if (!masterId.value) {
    ElMessage.warning('请先在顶部下拉选主控设备')
    return false
  }
  if (!slaveIds.value.length) {
    ElMessage.warning('请先勾选从机（底部多画面预览里勾选，或点顶部「全选」）')
    return false
  }
  return true
}

async function runBatchOpenUrl() {
  if (!needSlaves()) return
  if (!batchUrl.value) return ElMessage.warning('请输入 URL')
  const ids = broadcastTargets()
  try {
    const { data } = await api.batchOpenUrl(ids, batchUrl.value)
    ElMessage.success(`批量开网页：成功 ${data?.ok ?? 0}/${data?.total ?? ids.length}`)
  } catch (e) {
    ElMessage.error(e?.friendly || '批量开网页失败')
  }
}

async function runBatchText() {
  if (!needSlaves()) return
  if (!batchText.value) return ElMessage.warning('请输入文本')
  const ids = broadcastTargets()
  try {
    const { data } = await api.batchText(ids, batchText.value)
    ElMessage.success(`批量输入：成功 ${data?.ok ?? 0}/${data?.total ?? ids.length}`)
  } catch (e) {
    ElMessage.error(e?.friendly || '批量输入失败')
  }
}

async function runBatchInstall() {
  if (!needSlaves()) return
  if (!batchApk.value) return ElMessage.warning('请输入 APK URL')
  const ids = broadcastTargets()
  try {
    await ElMessageBox.confirm(
      `确定要向 ${ids.length} 台从机安装 APK？\n${batchApk.value}`,
      '批量安装 APK',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const { data } = await api.batchInstall(ids, batchApk.value)
    ElMessage.success(`批量安装：成功 ${data?.ok ?? 0}/${data?.total ?? ids.length}`)
  } catch (e) {
    ElMessage.error(e?.friendly || '批量安装失败')
  }
}

// ---------------- 生命周期 ----------------
onMounted(async () => {
  window.addEventListener('message', onFollowMessage)
  await store.refresh({ page_size: 100 })
  loadAllDeviceSnapshots()
  // ws-scrcpy 投屏服务探针（与 Control.vue 同链路：失败只是不显示投屏入口）
  try {
    const { data } = await api.health()
    wsScrcpyBase.value = data.ws_scrcpy_base || ''
  } catch {
    /* 探针失败不影响截图模式 */
  }
  // 默认主控 = store.list 第 1 台，从机池 = 空（强制用户先选主控再勾从机）
  if (!masterId.value && allDevices.value.length) {
    masterId.value = allDevices.value[0].id
    store.addAllSelectedId(masterId.value) // 主控自动进从机池
  }
  startSlavePolling()
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onFollowMessage)
  stopMasterPolling()
  stopSlavePolling()
})
</script>

<template>
  <div class="page">
    <!-- 顶部状态条 -->
    <div class="page-header">
      <div class="page-title">批量操控台</div>
      <div class="page-header-right">
        <el-tag type="info" effect="dark">
          共 {{ totalDeviceCount }} 台
        </el-tag>
        <span class="master-picker">
          <span class="picker-label">主控设备</span>
          <el-select
            :model-value="masterId"
            @update:model-value="onMasterChange"
            placeholder="选一台作主控"
            size="default"
            style="width: 220px"
            :disabled="!totalDeviceCount"
          >
            <el-option
              v-for="d in allDevices"
              :key="d.id"
              :label="`#${d.id} · ${d.name}`"
              :value="d.id"
            />
          </el-select>
        </span>
        <el-tag :type="slaveCount ? 'success' : 'info'" effect="dark">
          从机 {{ slaveCount }} 台
        </el-tag>
        <el-button size="small"
          :type="isAllSlaves ? 'warning' : 'primary'"
          :plain="!!isAllSlaves"
          :disabled="!totalDeviceCount"
          :loading="selectingAll"
          @click="isAllSlaves ? clearAllSlaves() : selectAllSlaves()">
          {{ isAllSlaves ? '清空从机' : `全选（${totalDeviceCount - 1}）` }}
        </el-button>
      </div>
    </div>

    <!-- 上面：主控画板 + 3 张 side-card -->
    <div v-if="allDevices.length" class="master-layout">
      <el-card shadow="never" class="master-card">
        <template #header>
          <div class="card-header">
            <span>
              <el-icon><Connection /></el-icon>
              主控画面
            </span>
            <span v-if="masterDevice" class="card-sub">
              {{ masterDevice.name }} · {{ masterDevice.width || '?' }} × {{ masterDevice.height || '?' }}
            </span>
          </div>
        </template>

        <div class="canvas-toolbar">
          <el-button
            v-for="k in KEY_MAP"
            :key="k.key"
            :icon="k.icon"
            size="small"
            :loading="broadcasting"
            @click="broadcastKey(k.key)"
          >
            {{ k.label }}
          </el-button>
          <el-button
            size="small"
            :type="embedStream ? 'danger' : 'success'"
            plain
            :disabled="scrcpyDisabled && !embedStream"
            @click="toggleEmbed"
          >
            {{ embedStream ? '退出投屏' : '投屏模式' }}
          </el-button>
        </div>

        <div class="phone-panel">
          <div class="phone-card">
            <div v-if="!masterId" class="canvas-empty">请先在顶部「主控设备」下拉选一台</div>
            <template v-else>
              <div
                v-if="embedStream"
                class="embed-frame"
                :style="{ aspectRatio: `${masterDevice?.width || 9} / ${masterDevice?.height || 16}` }"
              >
                <iframe
                  v-if="scrcpyUrl"
                  :src="scrcpyUrl"
                  class="embed-iframe"
                  allowfullscreen
                />
              </div>
              <PhoneFrame
                v-else-if="masterDevice"
                :device="masterDevice"
                :frame="masterFrame"
                :last-action="lastAction"
                clickable
                swipeable
                @tap="onMasterTap"
                @swipe="onMasterSwipe"
              />
              <div v-else class="canvas-empty canvas-loading">主控 {{ masterId }} 取帧中…</div>
            </template>
          </div>
          <div class="phone-hint">
            <el-icon><InfoFilled /></el-icon>
            {{ embedStream
              ? '投屏直连：点按/滑动直接操控主控并自动同步从机（需 ws-scrcpy 已打 follow 补丁）；虚拟按键广播主控+从机'
              : '本地截图模式（2s 刷新）；点击画板 = 点按，按住拖动 = 滑动（同步主控+从机）' }}
          </div>
          <div v-if="broadcasting" class="broadcasting-overlay-inline">
            <span>同步中…</span>
          </div>
        </div>

        <div class="canvas-tip">
          <el-icon><InfoFilled /></el-icon>
          点击 / 滑动 / 快捷键 → 同步到从机池（{{ slaveCount }} 台）；坐标自动按主控分辨率归一化。
        </div>
        <div class="canvas-footer">
          最近操作：{{ lastAction || '—' }}
        </div>
      </el-card>

      <div class="side-cards">
        <el-card shadow="never" class="side-card">
          <template #header>
            <div class="card-header">
              <span>① 一键批量开网页</span>
              <el-tag size="small" type="info">同步</el-tag>
            </div>
          </template>
          <el-input v-model="batchUrl" placeholder="https://…">
            <template #append>
              <el-button type="primary" @click="runBatchOpenUrl">下发</el-button>
            </template>
          </el-input>
        </el-card>

        <el-card shadow="never" class="side-card">
          <template #header>
            <div class="card-header">
              <span>② 批量输入文本</span>
              <el-tag size="small" type="info">同步</el-tag>
            </div>
          </template>
          <el-input v-model="batchText" type="textarea" :rows="2" placeholder="要输入文本" />
          <el-button type="primary" style="margin-top: 8px; width: 100%" @click="runBatchText">
            批量输入
          </el-button>
        </el-card>

        <el-card shadow="never" class="side-card">
          <template #header>
            <div class="card-header">
              <span>③ 批量安装 APK</span>
              <el-tag size="small" type="warning">异步</el-tag>
            </div>
          </template>
          <el-input v-model="batchApk" placeholder="APK URL（http/https）">
            <template #append>
              <el-button type="warning" @click="runBatchInstall">安装</el-button>
            </template>
          </el-input>
        </el-card>
      </div>
    </div>

    <!-- 下面：多画面预览（仿 Grid.vue 风格，勾选 = 加入从机池） -->
    <div v-if="allDevices.length" class="multi-preview">
      <div class="multi-preview-header">
        <span>
          多画面预览（{{ previewDevices.length }} 台 · 勾选框 = 加入从机池；蓝色描边 = 主控）
        </span>
        <div class="multi-preview-actions">
          <span class="muted">布局</span>
          <el-select v-model="gridN" style="width: 100px" size="small">
            <el-option v-for="n in gridOptions" :key="n" :label="`${n} × ${n}`" :value="n" />
          </el-select>
        </div>
      </div>
      <div class="multi-preview-grid" :style="{ gridTemplateColumns: `repeat(${gridN}, 1fr)` }">
        <div
          v-for="d in previewDevices"
          :key="d.id"
          class="preview-cell"
          :class="cellRole(d.id)"
        >
          <PhoneFrame
            :device="d"
            :frame="store.frames[d.id]"
            :last-action="store.lastActions[d.id]"
            selectable
            :selected="isMaster(d.id) || isSlave(d.id)"
            @toggle="toggleSlave(d.id)"
          />
          <span v-if="isMaster(d.id)" class="badge badge-master">主</span>
          <span v-else-if="isSlave(d.id)" class="badge badge-slave">从</span>
        </div>
      </div>
    </div>
    <div v-else class="empty-placeholder">
      <el-icon class="empty-icon"><InfoFilled /></el-icon>
      <div class="empty-title">正在加载设备列表…</div>
      <div class="empty-tip">如果长时间无响应，请检查后端服务是否正常运行。</div>
    </div>
  </div>
</template>

<style scoped>
.page-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.master-picker {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: #f0f7ff;
  border: 1px solid #b3d8ff;
  border-radius: 6px;
}
.picker-label {
  font-size: 12px;
  color: #0a84ff;
  font-weight: 600;
  white-space: nowrap;
}

.empty-placeholder {
  border: 2px dashed var(--card-border);
  border-radius: 12px;
  padding: 60px 24px;
  text-align: center;
  background: #fafbfc;
}
.empty-icon {
  font-size: 48px;
  color: var(--text-muted);
  margin-bottom: 12px;
}
.empty-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.empty-tip {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

/* 主控布局 */
.master-layout {
  display: grid;
  grid-template-columns: minmax(320px, 420px) 1fr;
  gap: 14px;
  margin-bottom: 14px;
}
.master-card {
  display: flex;
  flex-direction: column;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: 15px;
}
.card-sub {
  font-weight: 400;
  font-size: 12px;
  color: var(--text-muted);
}

.canvas-toolbar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.phone-panel {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  position: relative;
}
.phone-card {
  width: 100%;
  padding: 14px;
  background: linear-gradient(145deg, #f8fafc, #eef2ff);
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360px;
}
.phone-card :deep(.phone) {
  width: 100%;
  margin: 0;
  max-width: 320px;
}
/* 主控投屏容器：按主控真实分辨率定长宽比，iframe 铺满（ws-scrcpy 侧已打 CSS 补丁隐藏工具栏） */
.embed-frame {
  width: 100%;
  max-width: 320px;
  background: #000;
  border-radius: 22px;
  overflow: hidden;
}
.embed-iframe {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}
.phone-hint {
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  margin-top: 10px;
  line-height: 1.5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.broadcasting-overlay-inline {
  position: absolute;
  top: 24px;
  right: 24px;
  background: rgba(10, 132, 255, 0.9);
  color: #fff;
  font-weight: 600;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 12px;
  z-index: 5;
  pointer-events: none;
}
.canvas-empty {
  color: var(--text-muted);
  font-size: 14px;
  text-align: center;
  padding: 24px;
}
.canvas-loading {
  color: var(--text-muted);
}

.canvas-tip {
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.canvas-footer {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--card-border);
  font-size: 12px;
  color: var(--text-muted);
  word-break: break-all;
}

.side-cards {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.side-card {
  margin-bottom: 0;
}

/* 多画面预览 */
.multi-preview {
  background: var(--card-bg, #fff);
  border: 1px solid var(--card-border, #ebeef5);
  border-radius: 8px;
  padding: 10px 12px;
}
.multi-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.multi-preview-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.muted {
  color: var(--text-muted);
  font-size: 12px;
}
.multi-preview-grid {
  display: grid;
  gap: 10px;
  max-height: 600px;
  overflow-y: auto;
  padding: 2px;
}

/* 预览卡片角色描边 + 徽标 */
.preview-cell {
  position: relative;
  border-radius: 8px;
  padding: 2px;
  transition: outline-color 0.2s, box-shadow 0.2s;
}
.preview-cell.role-master {
  outline: 3px solid #0a84ff;
  outline-offset: 0;
  box-shadow: 0 0 12px rgba(10, 132, 255, 0.25);
}
.preview-cell.role-slave {
  outline: 3px solid #34c759;
  outline-offset: 0;
  box-shadow: 0 0 8px rgba(52, 199, 89, 0.18);
}
.badge {
  position: absolute;
  top: 6px;
  left: 6px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  z-index: 10;
  font-weight: 600;
  color: #fff;
  pointer-events: none;
  line-height: 1.4;
}
.badge-master {
  background: #0a84ff;
}
.badge-slave {
  background: #34c759;
}
</style>
