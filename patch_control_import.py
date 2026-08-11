path = r'E:\server_cloud_phone\frontend\src\views\Control.vue'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = "import { ws } from '../api/ws'"
new = "import { socket as ws } from '../api/ws'"

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK - Control.vue import fixed')
else:
    print('NOT FOUND')
    # Check what's around ws import
    idx = content.find("import {")
    if idx >= 0:
        print(content[idx:idx+150])