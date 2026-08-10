<script setup>
import { onMounted, onBeforeUnmount, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDevices } from '../stores/devices'
import PhoneFrame from '../components/PhoneFrame.vue'

const store = useDevices()
const router = useRouter()
const cols = ref(3) // 2/3/4 -> 2x2 / 3x3 / 4x4
const groupId = ref('')

const shown = computed(() => {
  let list = store.list
  if (groupId.value) list = list.filter((d) => d.group_id === groupId.value)
  return list
})

function resubscribe() {
  store.subscribePreviews(shown.value.map((d) => d.id), 1)
}

watch(shown, resubscribe)
watch(cols, resubscribe)

onMounted(async () => {
  await store.refresh()
  await store.refreshGroups()
  resubscribe()
})
onBeforeUnmount(() => store.subscribePreviews([], 1))
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <span style="font-weight: 600">多画面实时预览</span>
      <el-radio-group v-model="cols">
        <el-radio-button :value="2">2 × 2</el-radio-button>
        <el-radio-button :value="3">3 × 3</el-radio-button>
        <el-radio-button :value="4">4 × 4</el-radio-button>
      </el-radio-group>
      <el-select v-model="groupId" placeholder="全部分组" clearable style="width: 150px">
        <el-option v-for="g in store.groups" :key="g.id" :label="g.name" :value="g.id" />
      </el-select>
      <div class="spacer"></div>
      <el-tag type="info">共 {{ shown.length }} 台 · 点击画面进入单机操控</el-tag>
    </div>

    <div class="grid" :style="{ gridTemplateColumns: `repeat(${cols}, 1fr)` }">
      <PhoneFrame
        v-for="d in shown"
        :key="d.id"
        :device="d"
        :frame="store.frames[d.id]"
        :last-action="store.lastActions[d.id]"
        @open="router.push(`/device/${d.id}`)"
      />
    </div>
    <el-empty v-if="!shown.length" description="暂无设备，请先到「设备管理」批量建机" />
  </div>
</template>
