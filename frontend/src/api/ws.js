// WebSocket 客户端：订阅预览帧 + 接收设备状态/批量进度广播。
// 自动重连；对外暴露 on(type, handler) 订阅、subscribe(ids, fps) 订阅预览。

export class DeviceSocket {
  constructor() {
    this.ws = null
    this.handlers = {}
    this.sub = { device_ids: [], fps: 1 }
    this._timer = null
    // 连接状态回调：让界面能显示「实时通道已断开」。
    // 不加这个的话，WS 断了只是预览画面静止不动，用户看到的是「操作没反应」，
    // 而真实原因（推送通道断了）只出现在 console 里 —— 实测断网期间刷了 20+ 条
    // WebSocket 错误，界面上毫无体现。
    this.onState = null
    this.retries = 0
  }

  _state(s, detail = '') {
    if (this.onState) this.onState(s, detail)
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this._state(this.retries ? 'connecting' : 'connecting')
    try {
      this.ws = new WebSocket(`${proto}://${location.host}/api/ws`)
    } catch (e) {
      this._state('closed', e.message || 'WebSocket 创建失败')
      clearTimeout(this._timer)
      this._timer = setTimeout(() => this.connect(), 1500)
      return
    }
    this.ws.onopen = () => {
      this.retries = 0
      this._state('open')
      this._send({ type: 'subscribe', ...this.sub })
    }
    this.ws.onmessage = (ev) => {
      let msg
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      const hs = this.handlers[msg.type] || []
      hs.forEach((h) => h(msg))
    }
    this.ws.onclose = () => {
      this.retries += 1
      this._state('closed', `已重连 ${this.retries} 次未成功`)
      clearTimeout(this._timer)
      // 退避重连：1.5s 起、最多 10s，避免后端长时间不可用时每 1.5s 刷一条错误
      const delay = Math.min(10000, 1500 * Math.min(this.retries, 7))
      this._timer = setTimeout(() => this.connect(), delay)
    }
  }

  _send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj))
  }

  subscribe(deviceIds, fps = 1) {
    this.sub = { device_ids: deviceIds, fps }
    this._send({ type: 'subscribe', ...this.sub })
  }

  on(type, handler) {
    ;(this.handlers[type] ||= []).push(handler)
    return () => {
      this.handlers[type] = (this.handlers[type] || []).filter((h) => h !== handler)
    }
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj))
    }
  }

  close() {
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
    }
    clearTimeout(this._timer)
  }
}

export const socket = new DeviceSocket()
