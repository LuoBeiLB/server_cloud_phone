#!/usr/bin/env bash
# =============================================================================
# 部署 ws-scrcpy —— 对已 adb 纳管的 Redroid 设备做 H.264 低延迟 Web 投屏。
# 相比平台内置的截图轮询(~5-15fps PNG)，ws-scrcpy 走 scrcpy-server 的 H.264
# 编码 + 浏览器端解码(Broadway/MSE/WebCodecs)，更丝滑、更省带宽。
#
# 在 Linux 宿主机或 Lima VM 内运行：
#   bash deploy/scrcpy/setup-ws-scrcpy.sh
# 之后用 run-ws-scrcpy.sh 启动。
# =============================================================================
set -euo pipefail
WSDIR="${WSDIR:-$HOME/ws-scrcpy}"

echo "==> Node 20 + git"
command -v git  >/dev/null 2>&1 || sudo apt-get install -y -qq git
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
node --version

echo "==> 克隆 ws-scrcpy"
[ -d "$WSDIR/.git" ] || git clone --depth 1 https://github.com/NetrisTV/ws-scrcpy.git "$WSDIR"

echo "==> 安装依赖"
cd "$WSDIR"
npm install --no-audit --no-fund

# ---- 云手机平台内嵌投屏补丁：隐藏 ws-scrcpy 自带工具栏，视频铺满容器 ----
# 平台前端以 iframe 内嵌 ws-scrcpy 页面，跨域无法从外部改其样式，只能在
# 构建前改源码。自带工具栏的功能(电源/音量/导航/截图/键盘)已由平台前端在
# iframe 外提供。补丁幂等：已追加过则跳过。
CSS_FILE="$WSDIR/src/style/app.css"
if ! grep -q "cloud-phone embed" "$CSS_FILE" 2>/dev/null; then
  cat >> "$CSS_FILE" << 'EOF'

/* cloud-phone embed: hide builtin toolbar, let video fill the container */
.control-buttons-list { display: none !important; }
.device-view, .video { float: none !important; }
EOF
  echo "==> 已追加内嵌投屏 CSS 补丁到 $CSS_FILE"
fi
# ------------------------------------------------------------------------

echo "==> 构建(webpack，较久)"
npm run dist

echo "✅ 完成：$WSDIR/dist —— 用 run-ws-scrcpy.sh 启动"