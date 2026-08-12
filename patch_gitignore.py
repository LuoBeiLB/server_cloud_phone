path = r'E:\server_cloud_phone\.gitignore'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '*.apk\n\n# OS / editor'
new = '*.apk\n!backend/app/skins/ADBKeyboard.apk\n\n# OS / editor'

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK - .gitignore patched')
else:
    print('NOT FOUND')
    # Check what's around that area
    idx = content.find('*.apk')
    if idx >= 0:
        print('Found *.apk at', idx)
        print(repr(content[idx:idx+60]))