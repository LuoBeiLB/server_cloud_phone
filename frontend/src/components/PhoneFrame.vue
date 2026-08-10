<script setup>
import { computed } from 'vue'

const props = defineProps({
  device: { type: Object, required: true },
  frame: { type: String, default: '' },
  // 最近一次操作的可读描述。tap / swipe / 输入文本 这类操作画面上看不出变化，
  // 没有这行确认，用户点了按钮就以为「没反应」。
  lastAction: { type: String, default: '' },
  selectable: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false }, // 点击画面 -> 映射为设备坐标 tap
})
const emit = defineEmits(['open', 'toggle', 'tap'])

// 注意：不能用 btoa()，它无法编码中文（"加载中…"）会抛 InvalidCharacterError，
// 导致整个 PhoneFrame 渲染失败、预览页白屏。用 encodeURIComponent 生成 data URL 即可支持 Unicode。
const placeholder =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="410"><rect width="220" height="410" fill="#111"/><text x="110" y="205" fill="#666" font-size="14" text-anchor="middle">加载中…</text></svg>',
  )

const src = computed(() => props.frame || placeholder)

// 预览画布固定 440x820（后端渲染坐标系）；点击折算到设备真实分辨率
function onClick(e) {
  if (!props.clickable) return emit('open', props.device)
  const rect = e.currentTarget.getBoundingClientRect()
  const rx = (e.clientX - rect.left) / rect.width
  const ry = (e.clientY - rect.top) / rect.height
  emit('tap', {
    x: Math.round(rx * props.device.width),
    y: Math.round(ry * props.device.height),
  })
}
</script>

<template>
  <div class="phone" :style="{ outline: selected ? '3px solid #6366f1' : 'none' }" @click="onClick">
    <img :src="src" :alt="device.name" />
    <el-checkbox
      v-if="selectable"
      class="selbox"
      :model-value="selected"
      @change="$emit('toggle', device)"
      @click.stop
    />
    <div class="cap">
      <span class="dot" :class="device.status"></span>{{ device.name }}
      <span style="float: right; opacity: 0.85">{{ device.fingerprint?.network?.exit_ip }}</span>
    </div>
    <div v-if="lastAction && lastAction !== 'idle'" class="act" :title="lastAction">
      最近操作：{{ lastAction }}
    </div>
  </div>
</template>
