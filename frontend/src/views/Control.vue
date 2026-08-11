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
      : '低延迟 H.264 投屏，可直接操控（点按/滑动）',
)
const scrcpyDisabled = computed(() => !wsScrcpyBase.value || !device.value?.adb_port)

// 投屏地址（新窗口打开和内嵌共用同一份拼装逻辑，改一处两处同步）
const scrcpyUrl = computed(() => {
  if (scrcpyDisabled.value) return ''
  const udid = `localhost:${device.value.adb_port}`
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

// 内嵌投屏：把 H.264 实时画面直接嵌进手机框位置，ws-scrcpy 播放器自带
// 鼠标操控（点按/滑动），嵌入后手机窗口即可直接操作，无需再开新窗口。
// 开启时停掉截图预览订阅省带宽，关闭时恢复。
const embedStream = ref(false)
function toggleEmbed() {
  if (scrcpyDisabled.value) return ElMessage.warning(scrcpyTip.value)
  embedStream.value = !embedStream.value
  if (embedStream.value) {
    store.subscribePreviews([], 1)
  } else {
    subscribe()
  }
}
function openScrcpy() {
  if (scrcpyDisabled.value) return ElMessage.warning(scrcpyTip.value)
  window.open(scrcpyUrl.value, '_blank')
}

// 预览帧率：10-60 可选，改动立即重新订阅生效。
// 真机受后端 screencap ~64ms 物理限制，实际趋近 ~15fps；模拟器可跑满。
const fps = ref(10)
const fpsOptions = [10, 15, 20, 30, 45, 60]
function subscribe() {
  if (embedStream.value) return // 内嵌投屏期间不订截图帧
  store.subscribePreviews([id.value], fps.value)
}
watch(id, subscribe)
watch(fps, subscribe)
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
// 手机窗口拖动手势（控屏 swiper）：PhoneFrame 已把拖动轨迹换算成
// 设备坐标的 x1,y1 -> x2,y2 和实际拖动时长，直接透传给后端
async function onSwipe(p) {
  await ctl('swipe', p)
}
async function key(k) {
  await ctl('key', { key: k })
}

// ---------- 物理键盘同步 ----------
// 开启后，敲自己电脑的键盘 = 在手机上打字：可打印字符走 text 注入，
// 退格 / 回车 / 方向键映射为 keyevent（真机即 adb shell input ...）。
//
// 三个坑：
// 1. 监听挂 window 而不是画面元素 —— 点过画面后焦点不一定留在画面上，
//    挂 window 才稳；但必须过滤 e.target，否则在右侧网址框打字也会转发到手机。
// 2. 连打不能并发发请求：多个 POST 在路上的到达顺序不保证，会出乱序字。
//    用串行 Promise 队列保序，再加 40ms 小缓冲把连续字符合并成一段，
//    一句话往往只发 1-2 个请求，顺序和效率都保住。
// 3. e.isComposing（中文输入法组字中）必须跳过：转发半成品拼音会留残字。
//    且 adb input text 本身只支持 ASCII —— 中文请用右侧「文本输入」整段发送。
const kbdSync = ref(false)
let kbdQueue = Promise.resolve() // 串行队列
let kbdBuf = '' // 待发送的字符缓冲
let kbdBufTimer = null

function kbdSend(fn) {
  kbdQueue = kbdQueue.then(fn).catch(() => {})
}

function flushKbdBuf() {
  if (!kbdBuf) return
  const text = kbdBuf
  kbdBuf = ''
  // record: false —— 键盘同步是高频操作，逐段录进脚本会把录制列表刷屏
  kbdSend(() => ctl('text', { text }, { record: false }))
}

const KBD_KEYMAP = {
  Backspace: 'KEYCODE_DEL',
  Enter: 'enter',
  ArrowUp: 'KEYCODE_DPAD_UP',
  ArrowDown: 'KEYCODE_DPAD_DOWN',
  ArrowLeft: 'KEYCODE_DPAD_LEFT',
  ArrowRight: 'KEYCODE_DPAD_RIGHT',
}

function onKbdKeydown(e) {
  if (!kbdSync.value) return
  // 正在页面自己的输入框里打字（网址/文本/下拉搜索等）：不转发、不抢按键
  const t = e.target
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if (e.ctrlKey || e.metaKey || e.altKey) return // 组合快捷键留给浏览器
  if (e.isComposing) return // 中文组字中不转发

  const mapped = KBD_KEYMAP[e.key]
  if (mapped) {
    e.preventDefault()
    flushKbdBuf() // 特殊键之前先把缓冲的字符发出去，保住顺序
    kbdSend(() => ctl('key', { key: mapped }, { record: false }))
  } else if (e.key.length === 1) {
    e.preventDefault()
    kbdBuf += e.key
    clearTimeout(kbdBufTimer)
    kbdBufTimer = setTimeout(flushKbdBuf, 40)
  }
}

watch(kbdSync, (on) => {
  if (on) {
    window.addEventListener('keydown', onKbdKeydown)
    ElMessage.success('键盘已连接：直接打字即输入到手机（中文请用右侧文本框整段发送）')
  } else {
    window.removeEventListener('keydown', onKbdKeydown)
    flushKbdBuf()
  }
})
onBeforeUnmount(() => {
  if (kbdSync.value) window.removeEventListener('keydown', onKbdKeydown)
})

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
          <el-button
            :icon="'VideoCamera'"
            :type="embedStream ? 'danger' : 'default'"
            :disabled="scrcpyDisabled"
            @click="toggleEmbed"
          >
            {{ embedStream ? '关闭投屏' : '内嵌投屏(H.264)' }}
          </el-button>
        </span>
      </el-tooltip>
      <el-tooltip content="在新窗口打开投屏" placement="bottom">
        <span>
          <el-button :icon="'TopRight'" :disabled="scrcpyDisabled" circle @click="openScrcpy" />
        </span>
      </el-tooltip>
      <el-select v-model="fps" style="width: 100px; margin-right: 14px">
        <el-option v-for="f in fpsOptions" :key="f" :label="`${f} fps`" :value="f" />
      </el-select>
      <el-switch v-model="recording" active-text="录制中" inactive-text="录制脚本" />
      <el-button type="primary" :icon="'Download'" @click="saveScript">保存脚本 ({{ steps.length }})</el-button>
    </div>

    <div style="display: flex; gap: 26px; padding: 8px 0">
      <div style="width: 300px">
        <!-- 内嵌投屏模式：H.264 实时画面直接占住手机框位置，可点可滑 -->
        <div
          v-if="embedStream"
          style="
            width: 100%;
            background: #000;
            border-radius: 18px;
            overflow: hidden;
            border: 3px solid #1d1d1f;
          "
          :style="{ aspectRatio: `${device.width} / ${device.height}` }"
        >
          <iframe
            :src="scrcpyUrl"
            style="width: 100%; height: 100%; border: 0; display: block"
            allow="autoplay"
          ></iframe>
        </div>
        <!-- 预览帧模式：截图画面 + 手势操控（点按/滑动） -->
        <PhoneFrame
          v-else
          :device="device"
          :frame="store.frames[device.id]"
          :last-action="store.lastActions[device.id]"
          clickable
          swipeable
          @tap="onTap"
          @swipe="onSwipe"
        />
        <div style="text-align: center; color: #86868b; font-size: 12px; margin-top: 8px">
          {{ embedStream ? '投屏画面内直接点按/拖动即可操控' : '点击画面 = 点按；按住拖动 = 滑动（实时映射设备坐标）' }}
        </div>
        <!-- 物理键盘同步开关：开启后电脑键盘直接输入到手机 -->
        <div
          v-if="!embedStream"
          style="
            margin-top: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 10px;
            border-radius: 8px;
          "
          :style="kbdSync ? 'background: #e8f3ff; outline: 1px solid #0a84ff55' : 'background: #f5f5f7'"
        >
          <el-switch v-model="kbdSync" active-text="键盘同步" />
          <span style="color: #86868b; font-size: 12px; line-height: 1.4">
            {{
              kbdSync
                ? '已连接：打字=输入，支持退格/回车/方向键；中文用右侧文本框整段发'
                : '开启后敲电脑键盘直接输入到手机'
            }}
          </span>
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
          <el-input v-model="textInput" placeholder="输入文本后发送到焦点框（支持中文）" @keyup.enter="sendText">
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