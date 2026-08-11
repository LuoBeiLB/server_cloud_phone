<script setup>
/**
 * 系统自检 —— 一键 docker 部署的甲方自助排障入口。
 *
 * 设计取向：不做「绿灯一片」的装饰性看板。每一项失败都必须回答两个问题：
 *   1) 到底哪里不对（实测值 + 原因）
 *   2) 我该敲什么命令（处置，可一键复制）
 * 所以 fail/warn 默认展开、ok 默认收起，让人一眼看到需要动手的地方。
 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const loading = ref(false)
const data = ref(null)
const error = ref('')

const STATUS_META = {
  ok: { label: '正常', type: 'success', icon: '✓' },
  warn: { label: '注意', type: 'warning', icon: '!' },
  fail: { label: '故障', type: 'danger', icon: '✗' },
  unknown: { label: '无法判定', type: 'info', icon: '?' },
  skip: { label: '不适用', type: 'info', icon: '–' },
}

// 需要动手的项排在最前面，正常项垫底
const ORDER = { fail: 0, warn: 1, unknown: 2, ok: 3, skip: 4 }
const sortedChecks = computed(() =>
  [...(data.value?.checks || [])].sort((a, b) => ORDER[a.status] - ORDER[b.status]),
)
const actionable = computed(() =>
  sortedChecks.value.filter((c) => c.status === 'fail' || c.status === 'warn'),
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data: d } = await api.diagnostics()
    data.value = d
  } catch (e) {
    // 自检页本身失败也必须说清原因，否则就成了「打开自检页一片空白」
    const status = e.response?.status
    if (status !== 401) {
      error.value =
        e.response?.data?.detail ||
        e.message ||
        '自检接口无响应，后端可能未启动或 nginx 反代不通'
    }
  } finally {
    loading.value = false
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('处置命令已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-title">系统自检</div>
      <div class="page-header-right">
        <el-button type="primary" :loading="loading" :icon="'Refresh'" @click="load">
          重新自检
        </el-button>
      </div>
    </div>

    <div class="bar" v-if="data">
      <el-tag :type="STATUS_META[data.overall]?.type" size="large" effect="dark">
        总体：{{ STATUS_META[data.overall]?.label || data.overall }}
      </el-tag>
      <span class="muted">
        设备后端 <b>{{ data.backend }}</b> · 探测位置 <b>{{ data.probed_from }}</b>
      </span>
      <span class="muted">
        正常 {{ data.summary.ok }} · 注意 {{ data.summary.warn }} · 故障
        {{ data.summary.fail }} · 无法判定 {{ data.summary.unknown }}
      </span>
    </div>

    <el-alert v-if="error" type="error" :closable="false" show-icon class="mb">
      <template #title>自检接口调用失败</template>
      {{ error }}
      <div class="tip">
        排查顺序：① <code>docker compose ps</code> 看 backend 是否 healthy；②
        <code>curl -s http://localhost:5173/api/health</code> 若为 502 则是 nginx 反代到后端不通
        （只重新发布过 backend 时试 <code>docker exec cloud_frontend nginx -s reload</code>）。
      </div>
    </el-alert>

    <el-alert
      v-if="data && !actionable.length && !error"
      type="success"
      :closable="false"
      show-icon
      class="mb"
      title="所有检查项通过，没有需要处理的问题"
    />

    <el-alert
      v-if="data?.in_container"
      type="info"
      :closable="false"
      show-icon
      class="mb"
    >
      <template #title>关于「无法判定」的说明</template>
      后端跑在容器里，宿主机的内核设施（binder、/dev/dri）在容器内本来就看不见。
      这类项标为「无法判定」而不是「故障」——<b>容器里看不到不等于宿主机没有</b>，
      请按该项的处置建议在宿主机上直接确认。
    </el-alert>

    <el-card v-for="c in sortedChecks" :key="c.key" class="check" shadow="never">
      <div class="head">
        <el-tag :type="STATUS_META[c.status]?.type" effect="plain" size="small">
          {{ STATUS_META[c.status]?.icon }} {{ STATUS_META[c.status]?.label || c.status }}
        </el-tag>
        <b>{{ c.name }}</b>
        <span class="value">{{ c.value }}</span>
      </div>
      <div v-if="c.reason" class="reason">原因：{{ c.reason }}</div>
      <div v-if="c.hint" class="hint">
        <span class="hint-body">处置：{{ c.hint }}</span>
        <el-button link type="primary" size="small" @click="copy(c.hint)">复制</el-button>
      </div>
    </el-card>

    <el-empty v-if="!data && !loading && !error" description="尚未获取自检结果" />
  </div>
</template>

<style scoped>
.page {
  padding: 20px 24px;
}
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.muted {
  color: var(--text-muted);
  font-size: 13px;
}
.mb {
  margin-bottom: 12px;
}
.tip {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
}
.check {
  margin-bottom: 8px;
}
.check :deep(.el-card__body) {
  padding: 12px 14px;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.value {
  color: var(--text-secondary);
  font-size: 13px;
}
.reason {
  margin-top: 8px;
  font-size: 13px;
  color: var(--danger);
  line-height: 1.7;
  word-break: break-all;
}
.hint {
  margin-top: 6px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: #f1f5f9;
  border-radius: 4px;
  padding: 8px 10px;
}
.hint-body {
  flex: 1;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
  word-break: break-all;
}
code {
  background: #f1f5f9;
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
