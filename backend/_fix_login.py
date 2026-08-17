"""删除 styles.css 中旧登录样式（已迁移到 Login.vue scoped）"""
path = r"E:\server_cloud_phone\frontend\src\styles.css"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 删除旧登录样式块
old_styles = """.login-wrap {
  height: 100%; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #c026d3 100%);
}
.login-card {
  width: 420px; padding: 36px 32px;
  border-radius: 18px; background: #fff;
  box-shadow: 0 20px 60px rgba(0,0,0,.18), 0 4px 12px rgba(0,0,0,.08);
}
.login-head { display: flex; }
.login-logo { width: 58px; height: 58px; object-fit: contain; margin-bottom: 2px; margin-left: 100px;border-radius: 12px; }
.login-title { font-size: 22px; font-weight: 700; margin: 0 0 4px; }
.login-sub { color: var(--text-secondary); font-size: 13px; margin-bottom: 22px; }"""

if old_styles in content:
    content = content.replace(old_styles + "\n\n", "").replace(old_styles, "")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("styles.css OK")
else:
    print("未匹配到旧样式，可能已不存在")
