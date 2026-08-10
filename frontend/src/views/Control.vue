<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, markHandled } from '../api/client'
import { useDevices } from '../stores/devices'
import PhoneFrame from '../components/PhoneFrame.vue'

const route = useRoute()
const router = useRouter()
const store = useDevices()
const id = computed(() => Number(route.params.id))
const device = computed(() => store.byId(id.value))
const url = ref('')
const textInput = ref('')

// 脚本录制
const recording = ref(false)
const steps = ref([])
function rec(action, params) {
  if (recording.value) steps.value.push({ action, params })
}

// scrcpy 低延迟 H.264 投屏（ws-scrcpy）。
//
// 坑：这里原先写死 `http://<当前域名>:8100`，但 docker-compose 里**从来没有**
// ws-scrcpy 服务 —— 一键部署根本不会启动它。点按钮只会打开一个不存在的地址，
// 或误开宿主上恰好占用 8100 的别的服务，用户看到的就是「投屏不能用」。
// 现在地址由后端 CLOUD_WS_SCRCPY_BASE 提供：没配就置灰按钮并说明原因，
// 配了才可用 —— 宁可明确「未部署」，也不给一个点了必坏的按钮。
const wsScrcpyBase = ref('')
onMounted(async () => {
  try {
    const { data } = await api.health()
    wsScrcpyBase.value = data.ws_scrcpy_base || ''
  } catch {
    /* 探针失败不影响主功能；按钮保持禁用 */
  }
})
const scrcpyTip = computed(() =>
  !wsScrcpyBase.value
    ? '未部署 ws-scrcpy 投屏服务。部署后在后端设 CLOUD_WS_SCRCPY_BASE=http://<地址>:8100 即可启用'
    : !device.value?.adb_port
      ? '该设备无 adb 端口（模拟后端不支持 scrcpy 投屏）'
      : '低延迟 H.264 投屏（新窗口打开）',
)
const scrcpyDisabled = computed(() => !wsScrcpyBase.value || !device.value?.adb_port)

function openScrcpy() {
  if (scrcpyDisabled.value) return ElMessage.warning(scrcpyTip.value)
  const udid = `localhost:${device.value.adb_port}`
  const base = wsScrcpyBase.value.replace(/\/+$/, '')
  const wsProto = base.startsWith('https') ? 'wss' : 'ws'
  const innerWs =
    `${wsProto}://${base.replace(/^https?:\/\//, '')}` +
    `/?action=proxy-adb&remote=tcp:8886&udid=${encodeURIComponent(udid)}`
  window.open(
    `${base}/#!action=stream&udid=${encodeURIComponent(udid)}` +
      `&player=broadway&ws=${encodeURIComponent(innerWs)}`,
    '_blank',
  )
}

// 高清投屏：开启后拉到 ~12fps（后端 /screenshot ~64ms 能跟上），更接近视频流
const hd = ref(false)
function subscribe() {
  store.subscribePreviews([id.value], hd.value ? 12 : 5)
}
watch(id, subscribe)
watch(hd, subscribe)
onMounted(async () => {
  if (!device.value) await store.refresh()
  url.value = device.value?.current_url || ''
  subscribe()
})
onBeforeUnmount(() => store.subscribePreviews([], 1))

// 统一的操控请求包装。
//
// 坑（曾导致「点击操作完全无反应、连报错都没有」）：本页原先每个操作都是裸 await，
// 既无 try/catch 也无失败提示。而 api/client.js 的拦截器只对 401（登录失效）和
// 503（设备失联）弹提示，其余 4xx/5xx/超时只是 Promise.reject —— 在界面上就是
// 什么都不发生，用户无法区分「没点到」「后端挂了」「设备没执行」。
//
// 约定：401/503 交给拦截器统一提示，这里不重复弹；其余错误一律弹出具体 detail。
// grouping 让连点产生的相同错误合并计数，不刷屏。
// 录制步骤与成功提示都只在请求真正成功后才执行。
async function ctl(action, params, { ok, record = true } = {}) {
  try {
    await api.control(id.value, action, params)
    if (record) rec(action, params)
    if (ok) ElMessage.success(ok)
    return true
  } catch (e) {
    const status = e.response?.status
    if (status !== 401 && status !== 503) {
      // e.friendly 由 api/client.js 统一整理（含后端给的处置建议）
      ElMessage.error({
        message: `操作「${action}」失败：${e.friendly || e.message || '未知错误'}`,
        grouping: true,
        duration: 6000,
      })
    }
    markHandled(e) // 已提示，别让全局兜底再弹一次
    return false
  }
}

async function openUrl() {
  if (!url.value.trim()) return ElMessage.warning('请先填写网址')
  await ctl('open_url', { url: url.value }, { ok: '已打开网页' })
}
async function onTap(pt) {
  await ctl('tap', pt)
}
async function key(k) {
  await ctl('key', { key: k })
}

// CP-007 分辨率/DPI 运行时切换
const displayPresets = [
  { label: '720 × 1280 @320', width: 720, height: 1280, dpi: 320 },
  { label: '1080 × 1920 @480', width: 1080, height: 1920, dpi: 480 },
  { label: '1080 × 2400 @480', width: 1080, height: 2400, dpi: 480 },
  { label: '1440 × 3200 @560', width: 1440, height: 3200, dpi: 560 },
]
const displaySel = ref(0)
async function applyDisplay() {
  const p = displayPresets[displaySel.value]
  // record: false —— 分辨率切换不属于可回放的操作步骤，原先也没录进脚本
  const okDone = await ctl('display', { width: p.width, height: p.height, dpi: p.dpi }, { record: false })
  if (!okDone) return
  await store.refresh()
  ElMessage.success(`已切换分辨率 ${p.width}×${p.height} @${p.dpi}`)
}
async function swipe(dir) {
  const w = device.value?.width, h = device.value?.height
  if (!w || !h) return ElMessage.warning('设备尺寸未知，请刷新后重试')
  const p =
    dir === 'up'
      ? { x1: w / 2, y1: h * 0.8, x2: w / 2, y2: h * 0.3, duration_ms: 300 }
      : { x1: w / 2, y1: h * 0.3, x2: w / 2, y2: h * 0.8, duration_ms: 300 }
  await ctl('swipe', p)
}
async function sendText() {
  if (!textInput.value) return ElMessage.warning('请先输入要发送的文本')
  // 只有发送成功才清空输入框，失败时保留内容让用户可以重试
  if (await ctl('text', { text: textInput.value })) textInput.value = ''
}
async function saveScript() {
  if (!steps.value.length) return ElMessage.warning('还没有录到操作')
  let value
  try {
    // 用户点「取消」时 prompt 会 reject，那不是错误，静默返回即可
    ;({ value } = await ElMessageBox.prompt('脚本名称', '保存脚本', { inputValue: '开网页脚本' }))
  } catch {
    return
  }
  try {
    await api.createScript({ name: value, steps: steps.value })
  } catch (e) {
    const status = e.response?.status
    if (status !== 401) {
      ElMessage.error(`保存脚本失败：${e.response?.data?.detail || e.message || '未知错误'}`)
    }
    return // 保存失败时保留已录步骤，不要清空
  }
  ElMessage.success(`已保存 ${steps.value.length} 步，去「脚本回放」跨设备执行`)
  steps.value = []
  recording.value = false
}
</script>

<template>
  <div class="page" v-if="device">
    <div class="toolbar">
      <el-button :icon="'ArrowLeft'" @click="router.push('/devices')">返回</el-button>
      <span style="font-weight: 600">{{ device.name }}</span>
      <el-tag>{{ device.fingerprint?.device?.model }}</el-tag>
      <el-tag type="success">{{ device.fingerprint?.network?.exit_ip }}</el-tag>
      <div class="spacer"></div>
      <el-tooltip :content="scrcpyTip" placement="bottom">
        <span>
          <el-button :icon="'VideoCamera'" :disabled="scrcpyDisabled" @click="openScrcpy">
            scrcpy 投屏(H.264)
          </el-button>
        </span>
      </el-tooltip>
      <el-switch v-model="hd" active-text="高清投屏12fps" inactive-text="标准5fps" style="margin-right: 14px" />
      <el-switch v-model="recording" active-text="录制中" inactive-text="录制脚本" />
      <el-button type="primary" :icon="'Download'" @click="saveScript">保存脚本 ({{ steps.length }})</el-button>
    </div>

    <div style="display: flex; gap: 26px; padding: 8px 0">
      <div style="width: 300px">
        <PhoneFrame
          :device="device"
          :frame="store.frames[device.id]"
          :last-action="store.lastActions[device.id]"
          clickable
          @tap="onTap"
        />
        <div style="text-align: center; color: #86868b; font-size: 12px; margin-top: 8px">
          点击画面 = 触屏点击（实时映射到设备坐标）
        </div>
      </div>

      <div style="flex: 1; max-width: 520px">
        <el-card shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 10px">浏览器 / 网页</div>
          <el-input v-model="url" placeholder="https://…" @keyup.enter="openUrl">
            <template #append><el-button @click="openUrl">打开</el-button></template>
          </el-input>
        </el-card>

        <el-card shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 10px">导航与手势</div>
          <el-button-group>
            <el-button :icon="'Back'" @click="key('back')">返回</el-button>
            <el-button :icon="'HomeFilled'" @click="key('home')">主页</el-button>
            <el-button :icon="'Menu'" @click="key('menu')">菜单</el-button>
            <el-button :icon="'Files'" @click="key('recent')">最近</el-button>
          </el-button-group>
          <el-button-group style="margin-left: 12px">
            <el-button :icon="'Top'" @click="swipe('up')">上滑滚动</el-button>
            <el-button :icon="'Bottom'" @click="swipe('down')">下滑滚动</el-button>
          </el-button-group>
          <el-button-group style="margin-left: 12px">
            <el-button :icon="'Bell'" @click="key('notifications')">通知栏</el-button>
            <el-button :icon="'Setting'" @click="key('quicksettings')">控制中心</el-button>
            <el-button :icon="'ArrowUpBold'" @click="key('collapse')">收起</el-button>
          </el-button-group>
        </el-card>

        <el-card shadow="never" style="margin-bottom: 14px">
          <div style="font-weight: 600; margin-bottom: 10px">文本输入</div>
          <el-input v-model="textInput" placeholder="输入文本后发送到焦点框" @keyup.enter="sendText">
            <template #append><el-button @click="sendText">发送</el-button></template>
          </el-input>
        </el-card>

        <el-card shadow="never">
          <div style="font-weight: 600; margin-bottom: 10px">显示（分辨率 / DPI）</div>
          <el-select v-model="displaySel" style="width: 200px">
            <el-option v-for="(p, i) in displayPresets" :key="i" :label="p.label" :value="i" />
          </el-select>
          <el-button style="margin-left: 10px" @click="applyDisplay">应用</el-button>
          <span style="margin-left: 10px; color: #86868b; font-size: 12px">
            当前 {{ device.width }}×{{ device.height }} @{{ device.dpi }}
          </span>
        </el-card>
      </div>
    </div>
  </div>
</template>
