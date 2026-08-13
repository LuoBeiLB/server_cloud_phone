path = r'E:\server_cloud_phone\frontend\src\api\ws.js'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: trailing comma after send method
old1 = '''  send(obj) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(obj))
    }
  },

  close() {'''
new1 = '''  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj))
    }
  }

  close() {'''

if old1 in content:
    content = content.replace(old1, new1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK')
else:
    print('NOT FOUND')
    print(repr(content[content.find('send'):content.find('send')+120]))