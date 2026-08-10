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
</script>

<template>
  <el-container style="height: 100%">
    <el-aside width="210px" style="background: #1c1c1e; color: #fff">
      <div style="padding: 20px 18px; font-size: 17px; font-weight: 700">
        📱 云手机群控平台
      </div>
      <el-menu
        :default-active="route.path"
        router
        background-color="#1c1c1e"
        text-color="#c7c7cc"
        active-text-color="#0a84ff"
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
    </el-aside>
    <el-container>
      <el-header
        style="display: flex; align-items: center; background: #fff; border-bottom: 1px solid #ebeef5"
      >
        <span style="font-weight: 600">{{ route.meta.title || '主流程演示' }}</span>
        <div style="flex: 1"></div>
        <el-tag type="success" effect="plain" style="margin-right: 12px">
          在线设备 {{ devices.running.length }} / {{ devices.list.length }}
        </el-tag>
        <el-dropdown @command="logout">
          <span style="cursor: pointer">
            <el-icon><User /></el-icon> {{ auth.user?.username || 'admin' }}
          </span>
          <template #dropdown>
            <el-dropdown-menu><el-dropdown-item>退出登录</el-dropdown-item></el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <!-- 实时通道断开必须让用户看见。
           否则 WS 断了只是预览画面静止、状态不更新，用户体验到的是「操作没反应」，
           而真正的原因只出现在浏览器 console 里。 -->
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
      <!-- 设备列表加载失败：不要安静地展示旧数据 -->
      <el-alert
        v-if="devices.loadError"
        type="error"
        :closable="false"
        show-icon
        style="border-radius: 0"
        :title="`设备列表加载失败：${devices.loadError}`"
      />
      <el-main style="padding: 0; overflow: auto">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
