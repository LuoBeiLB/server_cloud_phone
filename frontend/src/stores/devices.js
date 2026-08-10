import { defineStore, acceptHMRUpdate } from 'pinia'
import { api } from '../api/client'
import { socket } from '../api/ws'

// 真机换肤落地阶段 → 展示文案（与后端 skin_progress 的 phase 对应）
export const SKIN_PHASE_TEXT = {
  queued: '排队等待',
  launcher: '装 iOS 启动器',
  grid: '布置 iOS 桌面',
  wallpaper: '写入壁纸',
  reboot: '重启生效中',
  prefs: '配置主题',
  done: '换肤完成',
  failed: '换肤失败',
}

// 预览帧来源有两条通道，互为兜底：
//  1) WebSocket 推送（快，但在部分本机代理 / 企业代理下 localhost 的 WS 会被劫持）
//  2) HTTP 轮询 /devices/{id}/screenshot（稳，走 axios + vite 代理，一定通）
// 当近 2.5s 内收到过 WS 帧，则认为 WS 健康，自动跳过 HTTP 轮询，避免重复请求。
let pollTimer = null

export const useDevices = defineStore('devices', {
  state: () => ({
    list: [],
    groups: [],
    frames: {}, // device_id -> data URL 预览帧
    lastActions: {}, // device_id -> 最近一次操作的可读描述（后端返回）
    batchProgress: null, // {action, done, total}
    skinProgress: {}, // device_id -> {phase, theme} 真机换肤落地进度（含重启）
    wsReady: false,
    lastWsFrameAt: 0, // 最近一次经 WS 收到预览帧的时间戳（ms）
    previewIds: [], // 当前正在预览的设备
    loadError: '', // 设备列表最近一次加载失败的原因（空 = 正常）
    wsState: 'connecting', // connecting | open | closed —— 供界面显示实时通道状态
    wsStateDetail: '', // 断开时的补充说明（重连次数等）
    wsClosedAt: 0, // 断开时刻，用于提示「画面可能不是最新」
  }),
  getters: {
    running: (s) => s.list.filter((d) => d.status === 'running'),
    byId: (s) => (id) => s.list.find((d) => d.id === id),
  },
  actions: {
    // refresh 被十几处调用（页面进入、操作成功后、WS 事件后）。
    // 它一抛异常，调用方后面的代码就全断了 —— 表现为「点了按钮什么都没发生」。
    // 这里吞掉异常但**必须留下痕迹**：拦截器已弹出提示，store 里记下失败标记，
    // 让页面能显示「数据可能不是最新」而不是安静地展示旧列表。
    async refresh(params) {
      try {
        const { data } = await api.listDevices(params)
        this.list = data
        this.loadError = ''
        return true
      } catch (e) {
        this.loadError = e.friendly || e.message || '设备列表加载失败'
        return false
      }
    },
    async refreshGroups() {
      try {
        const { data } = await api.listGroups()
        this.groups = data
        return true
      } catch {
        return false // 分组是辅助信息，失败不阻塞主流程；提示由拦截器统一给出
      }
    },
    upsert(device) {
      const i = this.list.findIndex((d) => d.id === device.id)
      if (i >= 0) this.list[i] = device
      else this.list.push(device)
    },
    remove(id) {
      this.list = this.list.filter((d) => d.id !== id)
    },
    initSocket() {
      if (this.wsReady) return
      // 把 WS 连接状态同步到 store，让界面能显示「实时通道断开」而不是画面静止
      socket.onState = (state, detail) => {
        this.wsState = state
        this.wsStateDetail = detail || ''
        if (state === 'closed' && !this.wsClosedAt) this.wsClosedAt = Date.now()
        if (state === 'open') this.wsClosedAt = 0
      }
      socket.connect()
      socket.on('device_status', (m) => this.upsert(m.device))
      socket.on('device_removed', (m) => this.remove(m.device_id))
      socket.on('preview', (m) => {
        this.lastWsFrameAt = Date.now()
        this.frames[m.device_id] = m.frame
      })
      socket.on('batch_progress', (m) => {
        this.batchProgress = m
      })
      socket.on('skin_progress', (m) => this._onSkinProgress(m))
      this.wsReady = true
    },
    _onSkinProgress(m) {
      this.skinProgress[m.device_id] = { phase: m.phase, theme: m.theme }
      // 终态（完成/失败）展示 6s 后自动消失
      if (m.phase === 'done' || m.phase === 'failed') {
        setTimeout(() => {
          if (this.skinProgress[m.device_id]?.phase === m.phase) delete this.skinProgress[m.device_id]
        }, 6000)
      }
    },
    // 页面加载时补齐「正在换肤」的设备状态（增量更新走 WS）
    async refreshSkinApplying() {
      try {
        const { data } = await api.getSkinApplying()
        const map = {}
        for (const it of data.applying || []) map[it.device_id] = { phase: it.phase, theme: it.theme }
        this.skinProgress = { ...map, ...this.skinProgress }
      } catch {
        /* 忽略：仅影响进度展示 */
      }
    },
    // 订阅预览：同时尝试 WS 推送 + HTTP 轮询。ids 为空则停止预览。
    // 单机/少量设备（≤3，如单机操控页）：直接高频 HTTP 轮询保证实时，不被 WS 抑制
    //   —— 后端 /screenshot 实测 ~64ms，可稳跑数 fps。
    // 多设备（网格）：WS 优先，HTTP 仅在 WS 不健康时兜底，避免同时打太多请求。
    subscribePreviews(ids, fps = 1) {
      socket.subscribe(ids, fps)
      this.previewIds = ids || []
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
      if (!this.previewIds.length) return

      // 下限 80ms → 单机「高清投屏」可到 ~10-12fps（后端 /screenshot ~64ms 能跟上）
      const interval = Math.max(80, Math.round(1000 / fps))
      const force = this.previewIds.length <= 3
      let busy = false
      const tick = async () => {
        if (busy) return
        if (!force && Date.now() - this.lastWsFrameAt < 2500) return
        busy = true
        try {
          await Promise.allSettled(
            this.previewIds.map(async (id) => {
              const { data } = await api.screenshot(id)
              this.frames[id] = data.frame
              // 让 tap/swipe/输入文本 这类画面无变化的操作也有可见确认
              if (data.last_action) this.lastActions[id] = data.last_action
            }),
          )
        } finally {
          busy = false
        }
      }
      tick()
      pollTimer = setInterval(tick, interval)
    },
  },
})

// 让本 store 支持热更新，避免开发时编辑 store 导致运行中页面状态损坏、子路由白屏
if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useDevices, import.meta.hot))
}
