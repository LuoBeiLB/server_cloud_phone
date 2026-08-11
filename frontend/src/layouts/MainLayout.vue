<script setup>
import { onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '../stores/auth'
import { useDevices } from '../stores/devices'

const router = useRouter()
const route = useRoute()
const auth = useAuth()
const devices = useDevices()

onMounted(() => {
  devices.initSocket()
  devices.refresh()
  devices.refreshGroups()
  if (!auth.user) auth.fetchMe().catch(() => {})
})

function logout() {
  auth.logout()
  router.push('/login')
}

const roleLabels = { superadmin: '超级管理员', admin: '管理员', operator: '操作员', viewer: '查看员' }
</script>

<template>
  <el-container style="height: 100%">
    <el-aside width="220px" class="sidebar">
      <div class="sidebar-logo">
        <div class="sidebar-logo-icon">📱</div>
        <div>
          <div class="sidebar-logo-title">云手机群控</div>
          <div class="sidebar-logo-sub">Cloud Console</div>
        </div>
      </div>
      <el-menu
        :default-active="route.path"
        router
        class="sidebar-menu"
        background-color="transparent"
        text-color="#94a3b8"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/dashboard"><el-icon><Odometer /></el-icon>数据看板</el-menu-item>
        <el-menu-item index="/devices"><el-icon><Iphone /></el-icon>设备管理</el-menu-item>
        <el-menu-item index="/groups"><el-icon><FolderOpened /></el-icon>分组管理</el-menu-item>
        <el-menu-item index="/grid"><el-icon><Grid /></el-icon>多画面预览</el-menu-item>
        <el-menu-item index="/batch"><el-icon><Operation /></el-icon>批量操控</el-menu-item>
        <el-menu-item index="/apps"><el-icon><Box /></el-icon>应用管理</el-menu-item>
        <el-menu-item index="/scripts"><el-icon><VideoPlay /></el-icon>脚本回放</el-menu-item>
        <el-menu-item index="/tasks"><el-icon><Timer /></el-icon>任务调度</el-menu-item>
        <el-menu-item index="/alerts"><el-icon><Warning /></el-icon>告警监控</el-menu-item>
        <el-menu-item index="/reports"><el-icon><Histogram /></el-icon>统计报表</el-menu-item>
        <el-menu-item index="/logs"><el-icon><Tickets /></el-icon>设备日志</el-menu-item>
        <el-menu-item index="/files"><el-icon><Upload /></el-icon>文件互传</el-menu-item>
        <el-menu-item index="/diagnostics"><el-icon><FirstAidKit /></el-icon>系统自检</el-menu-item>
        <template v-if="({ viewer: 1, operator: 2, admin: 3, superadmin: 4 }[auth.user?.role] || 0) >= 3">
          <el-menu-item index="/users"><el-icon><User /></el-icon>用户管理</el-menu-item>
          <el-menu-item index="/audit"><el-icon><Document /></el-icon>操作审计</el-menu-item>
        </template>
      </el-menu>
      <div class="sidebar-user">
        <div class="avatar">{{ (auth.user?.username || 'AD').slice(0, 2).toUpperCase() }}</div>
        <div class="info">
          <div class="name">{{ auth.user?.username || 'Admin' }}</div>
          <div class="role">{{ roleLabels[auth.user?.role] || '管理员' }}</div>
        </div>
        <el-icon style="color: #94a3b8; cursor: pointer" @click="logout"><Setting /></el-icon>
      </div>
    </el-aside>
    <el-container>
      <el-alert
        v-if="devices.wsState !== 'open'"
        :type="devices.wsState === 'closed' ? 'error' : 'warning'"
        :closable="false"
        show-icon
        style="border-radius: 0"
      >
        <template #title>
          <span v-if="devices.wsState === 'closed'">
            实时通道已断开，画面与设备状态可能不是最新
            <span v-if="devices.wsStateDetail">（{{ devices.wsStateDetail }}）</span>
            —— 正在自动重连；持续不恢复请到
            <router-link to="/diagnostics" style="color: inherit; text-decoration: underline">
              系统自检
            </router-link>
            查看后端与反代状态
          </span>
          <span v-else>实时通道连接中…</span>
        </template>
      </el-alert>
      <el-alert
        v-if="devices.loadError"
        type="error"
        :closable="false"
        show-icon
        style="border-radius: 0"
        :title="`设备列表加载失败：${devices.loadError}`"
      />
      <el-main style="padding: 0; overflow: auto; background: #f8fafc">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.sidebar {
  background: linear-gradient(180deg, #0f172a 0%, #1e1b4b 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-logo {
  display: flex; align-items: center; gap: 10px;
  padding: 18px 20px 14px;
}
.sidebar-logo-icon { font-size: 24px; }
.sidebar-logo-title { font-size: 16px; font-weight: 700; color: #fff; line-height: 1.2; }
.sidebar-logo-sub { font-size: 11px; color: #64748b; margin-top: 2px; }

.sidebar-menu {
  flex: 1; overflow-y: auto; border-right: none !important;
}
.sidebar-menu .el-menu-item {
  height: 42px; line-height: 42px; margin: 2px 8px;
  border-radius: 8px; font-size: 14px;
}
.sidebar-menu .el-menu-item:hover {
  background: rgba(99,102,241,.12) !important;
}
.sidebar-menu .el-menu-item.is-active {
  background: rgba(99,102,241,.25) !important;
  color: #fff !important; font-weight: 500;
}
.sidebar-menu .el-menu-item.is-active .el-icon {
  color: #818cf8;
}

.sidebar-user {
  margin: 8px 12px 12px; padding: 12px;
  border-radius: 10px; background: rgba(99,102,241,.15);
  display: flex; align-items: center; gap: 10px;
  flex-shrink: 0;
}
.sidebar-user .avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: #6366f1; display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: #fff; flex-shrink: 0;
}
.sidebar-user .info { flex: 1; min-width: 0; }
.sidebar-user .name { font-size: 13px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sidebar-user .role { font-size: 11px; color: #94a3b8; }
</style>
