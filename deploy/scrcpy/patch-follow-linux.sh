#!/usr/bin/env bash
# =============================================================================
# patch-follow-linux.sh —— 给已部署的 ws-scrcpy dist 注入 follow 事件补丁。
# 不动样式、不重跑构建、不重启服务：注入后浏览器 Ctrl+F5 强刷即可生效。
#
# 用法（113 服务器）：
#   bash patch-follow-linux.sh            # 默认 ~/ws-scrcpy
#   bash patch-follow-linux.sh /路径/ws-scrcpy
#
# 作用：往 dist/index.html 注入旁听脚本——iframe 内点按/滑动 postMessage
#       归一坐标给父页面，云手机平台「批量操控」页收到后广播到从机池。
#       （只加事件转发，不改任何 CSS/样式。）
# 幂等：已有补丁则跳过，重复执行安全。
# =============================================================================
set -euo pipefail
WSDIR="${1:-$HOME/ws-scrcpy}"
INDEX_FILE="$WSDIR/dist/index.html"
[ -f "$INDEX_FILE" ] || { echo "!! 找不到 $INDEX_FILE"; exit 1; }

python3 - "$INDEX_FILE" << 'PYEOF'
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
print("    浏览器端 Ctrl+F5 强刷生效")
PYEOF
