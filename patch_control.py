path = r'E:\server_cloud_phone\frontend\src\views\Control.vue'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add ws import
old1 = "import { api, markHandled } from '../api/client'"
new1 = "import { api, markHandled } from '../api/client'\nimport { ws } from '../api/ws'"
if old1 in content:
    content = content.replace(old1, new1)
else:
    print('STEP 1 NOT FOUND')
    exit(1)

# 2. Add keyboard state and handlers after textInput ref
old2 = "const textInput = ref('')"
new2 = '''const textInput = ref('')

// 键盘实时输入
const kbEnabled = ref(false)
let _kbBuf = ''
let _kbTimer = null
const KEY_EVENTS = new Set(['Enter','Backspace','Delete','Tab','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '])
function flushBuffer() {
  if (_kbBuf) {
    ws.send({ type: 'input_text', device_id: id.value, text: _kbBuf })
    _kbBuf = ''
  }
  if (_kbTimer) { clearTimeout(_kbTimer); _kbTimer = null }
}
function onKeyDown(e) {
  if (!kbEnabled.value) return
  if (KEY_EVENTS.has(e.key)) {
    flushBuffer()
    e.preventDefault()
    const map = { Enter:'enter', Backspace:'backspace', Delete:'delete', Tab:'tab', Escape:'escape', ArrowUp:'arrow_up', ArrowDown:'arrow_down', ArrowLeft:'arrow_left', ArrowRight:'arrow_right', ' ':'space' }
    ws.send({ type: 'key_event', device_id: id.value, key: map[e.key] || e.key.toLowerCase() })
    return
  }
  if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
    e.preventDefault()
    _kbBuf += e.key
    if (_kbTimer) clearTimeout(_kbTimer)
    _kbTimer = setTimeout(flushBuffer, 100)
  }
}
function toggleKeyboard() {
  kbEnabled.value = !kbEnabled.value
  _kbBuf = ''
  if (_kbTimer) { clearTimeout(_kbTimer); _kbTimer = null }
}'''
if old2 in content:
    content = content.replace(old2, new2)
else:
    print('STEP 2 NOT FOUND')
    exit(1)

# 3. Add keyboard switch in toolbar (after hd switch)
old3 = '<el-switch v-model="hd" active-text="高清投屏12fps" inactive-text="标准5fps" style="margin-right: 14px" />'
new3 = '''<el-switch v-model="hd" active-text="高清投屏12fps" inactive-text="标准5fps" style="margin-right: 14px" />
      <el-switch v-model="kbEnabled" active-text="键盘输入" inactive-text="键盘输入" style="margin-right: 14px" @change="toggleKeyboard" />'''
if old3 in content:
    content = content.replace(old3, new3)
else:
    print('STEP 3 NOT FOUND')
    exit(1)

# 4. Add tabindex and keydown on page div
old4 = '<div class="page" v-if="device">'
new4 = '<div class="page" v-if="device" tabindex="0" @keydown="onKeyDown">'
if old4 in content:
    content = content.replace(old4, new4)
else:
    print('STEP 4 NOT FOUND')
    exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('OK - Control.vue patched')