path = r'E:\server_cloud_phone\frontend\src\api\ws.js'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '  close() {'
new = '''  send(obj) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(obj))
    }
  },

  close() {'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK - ws.js patched')
else:
    print('NOT FOUND - ws.js')
    print(content[:200])