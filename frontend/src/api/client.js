import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api', timeout: 60000 })

// 注入 JWT
http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 401 自动登出：清 token → 提示 → 回登录页
//
// 坑（曾导致「页面空白、既不提示也不跳登录」）：只删 localStorage 是不够的。
// 路由守卫读的是 Pinia store 里的 token，store 只在创建时从 localStorage 取过一次，
// 删了 localStorage 后 store.isAuthed 仍为 true → 守卫把 /login 又弹回 /devices，
// 于是卡在一个请求全 401 的空页面上。必须同时清掉 store。
let handling401 = false
const unreachableToastAt = new Map() // device_id -> 上次提示时刻，节流用

// 高频轮询类请求不参与兜底提示，否则一断网就刷屏。
// 它们的失败由各自的可见性机制体现（预览画面冻结 + WS 断线横幅）。
const SILENT_PATHS = [/\/screenshot$/, /\/skin\/applying$/, /\/metrics/]
function isSilentPath(url) {
  return SILENT_PATHS.some((re) => re.test(url || ''))
}

/**
 * 把 axios 错误整理成一句「用户能看懂 + 知道下一步」的话。
 *
 * 后端的 DeviceProvisionError 会带 reason/hint（如「镜像未拉取」+ docker pull 命令），
 * 这里必须把 hint 透出来 —— 甲方是一键 docker 跑的，不看后端日志。
 */
export function describeError(err) {
  const res = err.response
  if (!res) {
    // 没有响应：后端没起来、nginx 反代不通、或网络断了
    const isTimeout = err.code === 'ECONNABORTED' || /timeout/i.test(err.message || '')
    return isTimeout
      ? '请求超时，后端无响应。检查 backend 容器是否在跑（docker compose ps）'
      : '连不上后端。检查 backend 是否 healthy；若 /api 返回 502，多为 nginx 反代到后端不通'
  }
  const d = res.data || {}
  // 云手机拉不起来：把「卡在哪一步 + 原因 + 处置」一起给出
  if (d.provision_failed) {
    return [d.detail || d.reason, d.hint && `处置：${d.hint}`].filter(Boolean).join(' ｜ ')
  }
  const detail =
    typeof d.detail === 'string'
      ? d.detail
      : Array.isArray(d.detail)
        ? d.detail.map((x) => x.msg || JSON.stringify(x)).join('；') // FastAPI 校验错误
        : ''
  // 502/503/504 且没有 JSON detail：说明请求没到后端，是 nginx 直接返回的错误页。
  // 这是「一键 docker」最常见的故障形态，必须直接给出处置，而不是干巴巴一个状态码。
  if (!detail && [502, 503, 504].includes(res.status)) {
    return (
      `后端无响应（HTTP ${res.status}），请求没有到达 backend。` +
      '排查：① docker compose ps 看 backend 是否 healthy；' +
      '② 若只重新发布过 backend，试 docker exec cloud_frontend nginx -s reload；' +
      '③ 详见「系统自检」页'
    )
  }
  const base = detail || `请求失败（HTTP ${res.status}）`
  return d.hint ? `${base} ｜ 处置：${d.hint}` : base
}

/** 业务代码自己弹过提示后调用，避免兜底重复提示。 */
export function markHandled(err) {
  if (err) err.__handled = true
  return err
}
http.interceptors.response.use(
  (r) => r,
  async (err) => {
    const status = err.response?.status
    const url = err.config?.url || ''
    // 登录接口自己返回的 401 是「账号密码错误」，交给登录页提示，别在这里抢话
    if (status === 401 && !url.includes('/auth/login') && !handling401) {
      handling401 = true
      localStorage.removeItem('token')
      try {
        const { useAuth } = await import('../stores/auth')
        useAuth().logout() // 关键：同步清掉 store，否则路由守卫仍认为已登录
      } catch {
        /* pinia 未就绪（极早期请求），localStorage 已清，跳转仍有效 */
      }
      ElMessage.warning('登录状态已失效，请重新登录')
      if (!location.hash.startsWith('#/login')) location.hash = '#/login'
      // 并发请求会一起 401，1 秒内只提示/跳转一次
      setTimeout(() => {
        handling401 = false
      }, 1000)
    }

    // 503 设备失联：明确告诉用户哪台掉了、怎么救，而不是让页面默默不动。
    // 取帧最高 12fps，同一台设备 10 秒内只提示一次，避免刷屏。
    if (status === 503 && err.response?.data?.unreachable) {
      const d = err.response.data
      const now = Date.now()
      if (now - (unreachableToastAt.get(d.device_id) || 0) > 10000) {
        unreachableToastAt.set(d.device_id, now)
        ElMessage.error({
          message: `设备 ${d.device_id} 已失联，画面与操作均不可用。${d.hint || ''}`,
          duration: 6000,
        })
      }
      return Promise.reject(err)
    }

    // 把错误整理成一句人能看懂的话，挂到 err.friendly 上供业务代码直接用
    err.friendly = describeError(err)

    // ---- 兜底：任何没被业务代码提示过的失败，都要弹出来 ----
    //
    // 背景：过去拦截器只处理 401/503，其余 4xx/5xx/网络错误只是 Promise.reject。
    // 若某个调用点忘了 catch（实测有十余处），界面上就是「点击毫无反应」，
    // 用户无法区分「没点到」「后端挂了」「设备没执行」。
    //
    // 判断「是否已提示过」用的是 DOM 里有没有 .el-message：延迟一小会儿再看，
    // 业务自己的 catch 若弹了提示，此时必然已在 DOM 中，兜底就让位。
    // 取舍：多个请求同时失败时，只保证至少有一条提示，不保证每条都弹 ——
    // 相比「静默」，少弹一条重复提示是可接受的代价。
    if (!isSilentPath(url)) {
      setTimeout(() => {
        if (err.__handled) return
        if (document.querySelector('.el-message')) return // 业务已经提示过了
        ElMessage.error({ message: err.friendly, duration: 6000, grouping: true })
      }, 260)
    }
    return Promise.reject(err)
  },
)

export const api = {
  // 鉴权
  login: (username, password) => http.post('/auth/login', { username, password }),
  me: () => http.get('/auth/me'),

  // 系统自检（排障入口）
  diagnostics: () => http.get('/diagnostics'),
  health: () => http.get('/health'),

  // 设备
  listDevices: (params) => http.get('/devices', { params }),
  getDevice: (id) => http.get(`/devices/${id}`),
  createDevice: (body) => http.post('/devices', body),
  batchCreate: (body) => http.post('/devices/batch', body),
  updateDevice: (id, body) => http.patch(`/devices/${id}`, body),
  deleteDevice: (id) => http.delete(`/devices/${id}`),
  batchDeleteDevices: (deviceIds) => http.post('/devices/batch/delete', { device_ids: deviceIds }),
  startDevice: (id) => http.post(`/devices/${id}/start`),
  stopDevice: (id) => http.post(`/devices/${id}/stop`),
  restartDevice: (id) => http.post(`/devices/${id}/restart`),
  screenshot: (id) => http.get(`/devices/${id}/screenshot`),

  // 分组
  listGroups: () => http.get('/groups'),
  createGroup: (body) => http.post('/groups', body),
  deleteGroup: (id) => http.delete(`/groups/${id}`),

  // 皮肤 · 一键换肤
  listSkinThemes: () => http.get('/skin/themes'),
  getSkinApplying: () => http.get('/skin/applying'),
  getSkin: (id, screen, theme) => http.get(`/skin/${id}`, { params: { screen, theme } }),
  applySkin: (id, theme) => http.post(`/skin/${id}`, { theme }),
  applySkinBatch: (deviceIds, theme) => http.post('/skin/batch', { device_ids: deviceIds, theme }),

  // 单机操控
  control: (id, action, body) => http.post(`/devices/${id}/control/${action}`, body),

  // 批量（1 控 N / 群控）
  // 通用方法保留：业务代码可调 api.batch('open_url', { device_ids, url })
  batch: (action, body) => http.post(`/batch/${action}`, body),
  // 具体方法（Batch.vue 用的就是这些）：坐标由后端按主控分辨率归一化后分发到各从机
  batchOpenUrl: (device_ids, url) => http.post('/batch/open_url', { device_ids, url }),
  batchTap: (device_ids, x, y) => http.post('/batch/tap', { device_ids, x, y }),
  batchSwipe: (device_ids, x1, y1, x2, y2, duration_ms = 300) =>
    http.post('/batch/swipe', { device_ids, x1, y1, x2, y2, duration_ms }),
  batchText: (device_ids, text) => http.post('/batch/text', { device_ids, text }),
  batchKey: (device_ids, key) => http.post('/batch/key', { device_ids, key }),
  batchInstall: (device_ids, apk_url) => http.post('/batch/install', { device_ids, apk_url }),

  // 脚本
  listScripts: () => http.get('/scripts'),
  createScript: (body) => http.post('/scripts', body),
  deleteScript: (id) => http.delete(`/scripts/${id}`),
  runScript: (id, deviceIds) => http.post(`/scripts/${id}/run`, { device_ids: deviceIds }),
}

export default http
