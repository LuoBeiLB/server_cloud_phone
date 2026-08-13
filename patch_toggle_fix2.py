path = r'E:\server_cloud_phone\frontend\src\views\Control.vue'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the toggleKeyboard function, replace with watch
old = "function toggleKeyboard() {\n  kbEnabled.value = !kbEnabled.value\n  _kbBuf = ''\n  if (_kbTimer) { clearTimeout(_kbTimer); _kbTimer = null }\n}"
new = "watch(kbEnabled, (val) => {\n  if (val) {\n    _kbBuf = ''\n    if (_kbTimer) { clearTimeout(_kbTimer); _kbTimer = null }\n  }\n})"

if old in content:
    content = content.replace(old, new)
    # Also remove @change="toggleKeyboard" from the switch
    content = content.replace(' @change="toggleKeyboard"', '')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    # Try to find what's actually there
    idx = content.find('toggleKeyboard')
    if idx >= 0:
        print('FOUND at', idx)
        print(repr(content[idx:idx+200]))
    else:
        print('toggleKeyboard NOT FOUND in file')