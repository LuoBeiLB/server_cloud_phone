#!/usr/bin/env bash
# =============================================================================
# 部署 ws-scrcpy —— 对已 adb 纳管的 Redroid 设备做 H.264 低延迟 Web 投屏。
# 相比平台内置的截图轮询(~5-15fps PNG)，ws-scrcpy 走 scrcpy-server 的 H.264
# 编码 + 浏览器端解码(Broadway/MSE/WebCodecs)，更丝滑、更省带宽。
#
# v3 变更（相对 v2）：
#   构建后向 dist/index.html 注入 follow 事件补丁：iframe 内点按/滑动
#   postMessage 给父页面，供云手机平台「批量操控」页广播到从机池。
#   只加事件转发，不改任何 CSS/样式。
#   对已部署不重跑本脚本的机器，可用 patch-follow-linux.sh 单独注入。
#
# 在 Linux 宿主机或 Lima VM 内运行：
#   bash deploy/scrcpy/setup-ws-scrcpy.sh
# 之后用 run-ws-scrcpy.sh 启动。
# =============================================================================
set -euo pipefail
WSDIR="${WSDIR:-$HOME/ws-scrcpy}"

echo "===> Node 20 + git"
command -v git  >/dev/null 2>&1 || sudo apt-get install -y -qq git
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
node --version

echo "===> 克隆 ws-scrcpy"
[ -d "$WSDIR/.git" ] || git clone --depth 1 https://github.com/NetrisTV/ws-scrcpy.git "$WSDIR"

echo "===> 安装依赖"
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
  echo "===> 已追加内嵌投屏 CSS 补丁到 $CSS_FILE"
fi
# ------------------------------------------------------------------------

# ---- 内嵌投屏 v2 补丁：全链铺满 html→body→#root→.App→.device-view→video ----
# v1 只隐藏工具栏，ws-scrcpy 页面自身布局链没有撑满，iframe 里视频只占一角。
# v2 把整条链 100% 撑满 + video object-fit: contain 居中等比。幂等：跳过已注入。
if ! grep -q "cloud-phone embed v2" "$CSS_FILE" 2>/dev/null; then
  cat >> "$CSS_FILE" << 'EOF'

/* cloud-phone embed v2: full-chain fill html→body→#root→.App→.device-view→video */
.control-buttons-list { display: none !important; }
html, body, #root, .App, .app { height: 100% !important; width: 100% !important; margin: 0 !important; padding: 0 !important; }
.device-view { display: block !important; position: absolute !important; top: 0; left: 0; right: 0; bottom: 0; float: none !important; }
.device-view video, .device-view .video, video { width: 100% !important; height: 100% !important; max-width: 100% !important; max-height: 100% !important; object-fit: contain !important; position: absolute !important; top: 0; left: 0; }
EOF
  echo "===> 已追加 v2 全链铺满 CSS 补丁到 $CSS_FILE"
fi
# ------------------------------------------------------------------------

echo "===> 构建(webpack，较久)"
npm run dist

# ---- v3 follow 事件补丁：注入 dist/index.html（幂等） ----
# 平台「批量操控」页以 iframe 内嵌本服务，跨域拿不到内部事件；
# 注入脚本旁听 pointer 事件，postMessage 归一坐标给父页面 → 广播从机。
INDEX_FILE="$WSDIR/dist/index.html"
python3 - "$INDEX_FILE" << 'PYEOF' || echo "!! follow 补丁注入失败，可稍后用 patch-follow-linux.sh 手动注入"
import pathlib, sys
p = pathlib.Path(sys.argv[1])
html = p.read_text(encoding="utf-8")
if "cp-scrcpy-follow" in html:
    print("已有 follow 补丁，跳过"); raise SystemExit(0)
JS = """<script data-cp-follow>
/* cloud-phone follow v3: forward iframe taps/swipes to parent (slave broadcast) */
(function () {
  if (window.__cpFollow) return; window.__cpFollow = true;
  function rect() {
    var els = document.querySelectorAll(".device-view canvas, .device-view video, canvas, video");
    for (var i = 0; i < els.length; i++) {
      var r = els[i].getBoundingClientRect();
      if (r.width > 2 && r.height > 2) return r;
    }
    return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  }
  function norm(e) {
    var r = rect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  }
  var sx = 0, sy = 0, st0 = 0;
  document.addEventListener("pointerdown", function (e) {
    if (!e.isPrimary) return;
    var p = norm(e); sx = p.x; sy = p.y; st0 = Date.now();
  }, true);
  document.addEventListener("pointerup", function (e) {
    if (!e.isPrimary) return;
    var p = norm(e);
    var dx = Math.abs(p.x - sx), dy = Math.abs(p.y - sy);
    var dur = Date.now() - st0;
    var msg = (Math.max(dx, dy) > 0.02 && dur < 1500)
      ? { type: "cp-scrcpy-follow", kind: "swipe", x1: sx, y1: sy, x2: p.x, y2: p.y, dur: dur }
      : { type: "cp-scrcpy-follow", kind: "tap", x: p.x, y: p.y };
    try { window.parent.postMessage(msg, "*"); } catch (err) {}
  }, true);
})();
</script>"""
if "</body>" not in html:
    print("!! index.html 无 </body>，追加到文件尾"); html = html + JS
else:
    html = html.replace("</body>", JS + "</body>", 1)
p.write_text(html, encoding="utf-8")
print("==> 已注入 follow 事件补丁:", p)
PYEOF
# ------------------------------------------------------------------------

echo "✅ 完成：$WSDIR/dist —— 用 run-ws-scrcpy.sh 启动"
