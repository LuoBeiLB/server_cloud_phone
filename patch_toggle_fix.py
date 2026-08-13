path = r'E:\server_cloud_phone\frontend\src\views\Control.vue'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix toggleKeyboard - remove the toggle since v-model already handles it
old = '''function toggleKeyboard() {
  kbEnabled.value = !kbEnabled.value
  _kbBuf = ''
  if (_kbTimer) { clearTimeout(_kbTimer); _kbTimer = null }
}'''
new = '''function toggleKeyboard(val) {
  _kbBuf = ''
  if (_kbTimer) { clearTimeout(_kbTimer); _kbTimer = null }
}'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('NOT FOUND')
    # show what's around toggleKeyboard
    idx = content.find('toggleKeyboard')
    if idx >= 0:
        print(content[idx:idx+300])