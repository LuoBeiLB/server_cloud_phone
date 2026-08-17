import { createRouter, createWebHashHistory } from 'vue-router'
import { nextTick } from 'vue'
import { ElMessage, ElLoading } from 'element-plus'
import { useAuth } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    redirect: '/devices',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'devices', name: 'devices', component: () => import('../views/Devices.vue') },
      { path: 'grid', name: 'grid', component: () => import('../views/Grid.vue') },
      { path: 'batch', name: 'batch', component: () => import('../views/Batch.vue') },
      { path: 'scripts', name: 'scripts', component: () => import('../views/Scripts.vue') },
      { path: 'tasks', name: 'tasks', component: () => import('../views/Tasks.vue') },
      { path: 'alerts', name: 'alerts', component: () => import('../views/Alerts.vue') },
      { path: 'reports', name: 'reports', component: () => import('../views/Reports.vue') },
      { path: 'logs', name: 'logs', component: () => import('../views/Logs.vue') },
      { path: 'files', name: 'files', component: () => import('../views/FileManager.vue') },
      { path: 'users', name: 'users', component: () => import('../views/Users.vue') },
      { path: 'audit', name: 'audit', component: () => import('../views/Audit.vue') },
      { path: 'apps', name: 'apps', component: () => import('../views/AppManager.vue') },
      { path: 'groups', name: 'groups', component: () => import('../views/Groups.vue') },
      {
        path: 'diagnostics',
        name: 'diagnostics',
        component: () => import('../views/Diagnostics.vue'),
      },
      { path: 'device/:id', name: 'control', component: () => import('../views/Control.vue') },
      { path: 'detail/:id', name: 'detail', component: () => import('../views/DeviceDetail.vue') },
    ],
  },
]

const router = createRouter({ history: createWebHashHistory(), routes })

// 全局路由切换 loading：切换时显示全屏遮罩，目标页面 DOM 渲染完成后关闭
let loadingInstance = null

function openPageLoading() {
  if (loadingInstance) return
  loadingInstance = ElLoading.service({ fullscreen: true, text: '页面加载中...' })
}

function closePageLoading() {
  if (!loadingInstance) return
  loadingInstance.close()
  loadingInstance = null
}

router.beforeEach((to) => {
  openPageLoading()
  const auth = useAuth()
  if (to.name !== 'login' && !auth.isAuthed) return { name: 'login' }
  if (to.name === 'login' && auth.isAuthed) return { name: 'devices' }
})

router.afterEach(() => {
  nextTick(() => {
    closePageLoading()
  })
})

// 懒加载 chunk 拉取失败 —— 重新发布后的头号「点击无反应」。
//
// 所有页面都是 `() => import(...)` 懒加载，chunk 文件名带内容哈希。重新发布后
// 旧 chunk 随镜像消失，而浏览器可能还缓存着旧的 index.html，于是请求一个已不存在的
// chunk：动态 import 的 promise 被拒 → vue-router 导航静默中止 → 页面空白/点了没反应，
// 错误只出现在 console 里。
//
// nginx 侧已修掉「404 被伪装成 200 + HTML」（见 deploy/nginx/default.conf），
// 这里再补用户侧：明确告知并自动刷新一次拿最新版本。
const CHUNK_ERR = /dynamically imported module|Importing a module script failed|Failed to fetch dynamically/i
const RELOAD_KEY = 'chunk-reload-at'

router.onError((err) => {
  closePageLoading()
  if (!CHUNK_ERR.test(err?.message || '')) return
  const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0)
  // 10s 内不重复刷新，避免「刷新→仍失败→再刷新」的死循环
  if (Date.now() - last < 10000) {
    ElMessage.error({
      message: '页面资源加载失败，且自动刷新后仍未恢复。请手动强制刷新（Ctrl/Cmd+Shift+R）；'
        + '若仍不行，说明前端资源未正确发布，请重建前端镜像',
      duration: 0,
      showClose: true,
    })
    return
  }
  sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
  ElMessage.warning({ message: '检测到前端已更新，正在重新加载最新版本…', duration: 1500 })
  setTimeout(() => location.reload(), 600)
})

export default router
