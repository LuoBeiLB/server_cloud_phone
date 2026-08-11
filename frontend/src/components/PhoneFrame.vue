<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  device: { type: Object, required: true },
  frame: { type: String, default: '' },
  // 最近一次操作的可读描述。tap / swipe / 输入文本 这类操作画面上看不出变化，
  // 没有这行确认，用户点了按钮就以为「没反应」。
  lastAction: { type: String, default: '' },
  selectable: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false }, // 点击画面 -> 映射为设备坐标 tap
  swipeable: { type: Boolean, default: false }, // 按住拖动画面 -> 映射为设备坐标 swipe
})
const emit = defineEmits(['open', 'toggle', 'tap', 'swipe'])

// 注意：不能用 btoa()，它无法编码中文（"加载中…"）会抛 InvalidCharacterError，
// 导致整个 PhoneFrame 渲染失败、预览页白屏。用 encodeURIComponent 生成 data URL 即可支持 Unicode。
const placeholder =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="410"><rect width="220" height="410" fill="#111"/><text x="110" y="205" fill="#666" font-size="14" text-anchor="middle">加载中…</text></svg>',
  )

const src = computed(() => props.frame || placeholder)

// ---------- 控屏手势层：短按 = tap，拖动 = swipe ----------
//
// 三个坑，都是踩过的：
// 1. img 必须 draggable="false"：浏览器原生拖图会吞掉 mouseup，手势丢终结，
//    表现为「偶尔滑了没反应」。
// 2. pointerup 必须挂在 window 上（once）：鼠标很容易拖出手机框外才松开，
//    只监听元素内部会漏掉抬起事件，手势卡住。
// 3. tap/swipe 判定阈值按设备像素走（短边 4%），不能用画布像素 ——
//    画布随窗口缩放，固定 px 阈值在不同缩放下手感不一致。
const gesture = ref(null) // { rx, ry, t } 起点（相对坐标 0~1）+ 按下时间戳
const ghost = ref(null) // 拖动中的当前点（相对坐标），用于画轨迹线
const gestureEl = ref(null) // 按下时的目标元素，抬起/移动时复算坐标用

function relPos(e, el) {
  const rect = el.getBoundingClientRect()
  return {
    rx: Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1),
    ry: Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1),
  }
}

function onPointerDown(e) {
  if (!props.clickable && !props.swipeable) return
  gestureEl.value = e.currentTarget
  gesture.value = { ...relPos(e, gestureEl.value), t: Date.now() }
  ghost.value = null
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp, { once: true })
}

function onPointerMove(e) {
  if (!gesture.value || !gestureEl.value) return
  ghost.value = relPos(e, gestureEl.value)
}

function onPointerUp(e) {
  window.removeEventListener('pointermove', onPointerMove)
  const s = gesture.value
  gesture.value = null
  ghost.value = null
  if (!s || !gestureEl.value) return
  const cur = relPos(e, gestureEl.value)
  const W = props.device.width
  const H = props.device.height
  const x1 = Math.round(s.rx * W)
  const y1 = Math.round(s.ry * H)
  const x2 = Math.round(cur.rx * W)
  const y2 = Math.round(cur.ry * H)
  const dist = Math.hypot(x2 - x1, y2 - y1)
  const dt = Date.now() - s.t
  const threshold = Math.min(W, H) * 0.04
  if (dist < threshold) {
    // 位移很小（含长按不动）：按点按处理，和旧行为一致
    if (props.clickable) emit('tap', { x: x1, y: y1 })
  } else if (props.swipeable) {
    // 真实拖动时长太短的滑动设备端容易丢，<80ms 兜底；太长的蓄力滑也没意义，封顶 1.5s
    emit('swipe', { x1, y1, x2, y2, duration_ms: Math.min(Math.max(dt, 80), 1500) })
  }
}

onBeforeUnmount(() => window.removeEventListener('pointermove', onPointerMove))

// 预览画布固定 440x820（后端渲染坐标系）；点击折算到设备真实分辨率。
// 注意：clickable/swipeable 模式下 tap 已由手势层统一发出，这里只处理
// 「非交互场景」的点击打开详情（Grid/Batch 页的行为），别重复发 tap。
function onClick() {
  if (!props.clickable && !props.swipeable) emit('open', props.device)
}
</script>

<template>
  <div
    class="phone"
    :style="{
      outline: selected ? '3px solid #0a84ff' : 'none',
      userSelect: 'none',
      cursor: clickable || swipeable ? 'crosshair' : 'pointer',
    }"
    @click="onClick"
    @pointerdown="onPointerDown"
  >
    <img :src="src" :alt="device.name" draggable="false" />
    <!-- 拖动轨迹：起点圆点 + 起点到当前点的连线，松手即消失 -->
    <template v-if="gesture && ghost">
      <svg
        style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none"
        viewBox="0 0 1 1"
        preserveAspectRatio="none"
      >
        <line
          :x1="gesture.rx"
          :y1="gesture.ry"
          :x2="ghost.rx"
          :y2="ghost.ry"
          stroke="#0a84ff"
          stroke-width="3"
          stroke-linecap="round"
          vector-effect="non-scaling-stroke"
          opacity="0.9"
        />
      </svg>
      <div
        :style="{
          position: 'absolute',
          left: `calc(${gesture.rx * 100}% - 7px)`,
          top: `calc(${gesture.ry * 100}% - 7px)`,
          width: '14px',
          height: '14px',
          borderRadius: '50%',
          background: 'rgba(10,132,255,0.85)',
          border: '2px solid #fff',
          pointerEvents: 'none',
        }"
      ></div>
    </template>
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