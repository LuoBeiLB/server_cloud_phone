#!/usr/bin/env bash
# =============================================================================
# 一键起栈并**打印访问地址** —— `docker compose up -d` 本身不会告诉你去哪访问，
# 实测甲方现场第一反应就是「起完了，然后呢？」。本脚本只做两件事：
#   1) 跑与生产完全相同的那条 compose 命令
#   2) 起完后打印所有服务的访问地址（用宿主真实 IP，不是 localhost）
#
#     bash deploy/scripts/up.sh              # 起真机（默认）
#     bash deploy/scripts/up.sh --simulator  # 无真机条件时降级
#     bash deploy/scripts/up.sh --urls       # 只打印地址，不动服务
#     bash deploy/scripts/up.sh --down       # 停（保留数据卷）
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

FILES=(-f docker-compose.yml)
[[ "${1:-}" == "--simulator" ]] && FILES+=(-f docker-compose.simulator.yml)

host_ip() {
  # 宿主对外 IP：优先默认路由所用地址，回退 hostname -I 第一个
  ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1);exit}}' \
    || hostname -I 2>/dev/null | awk '{print $1}' \
    || echo "127.0.0.1"
}

print_urls() {
  local ip; ip="$(host_ip)"
  [[ -n "$ip" ]] || ip=127.0.0.1
  cat <<EOF

═══════════════════════════════════════════════════════════════
  服务已就绪，访问地址：

  ▸ 管理控制台      http://${ip}:5173        ← 平时用这个
        账号 admin / 密码 admin123（首次启动自动创建）
  ▸ 系统自检        http://${ip}:5173/#/diagnostics
        起不来 / 点了没反应，先看这里，会直接给出原因与处置
  ▸ 后端 API 文档   http://${ip}:8000/docs
  ▸ 健康探针        http://${ip}:8000/api/health   （免登录）

  仅调试用（生产建议在 compose 里去掉对外暴露）：
  ▸ PostgreSQL      ${ip}:5432   账号/密码/库名均为 cloud
  ▸ Redis           ${ip}:6379

  常用：
      docker compose ps                 看容器状态
      docker compose logs -f backend    看后端日志
      bash deploy/scripts/up.sh --down  停服务（保留数据）
═══════════════════════════════════════════════════════════════
EOF
}

case "${1:-}" in
  --urls) print_urls; exit 0 ;;
  --down)
    docker compose "${FILES[@]}" down
    echo "已停止（数据卷保留；要连数据一起删用 docker compose down -v）"
    exit 0
    ;;
esac

echo "==> 拉起服务（首次构建较慢，国内已默认走镜像源）"
docker compose "${FILES[@]}" up -d --build --wait
echo
docker compose "${FILES[@]}" ps --format 'table {{.Name}}\t{{.Status}}'
print_urls
