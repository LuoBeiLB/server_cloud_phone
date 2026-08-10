#!/usr/bin/env bash
# =============================================================================
# macOS 开发机上一键拉起**真机**环境（Redroid）。
#
#     bash deploy/scripts/dev-up-real.sh          # 起
#     bash deploy/scripts/dev-up-real.sh --down   # 停（保留 VM 与镜像）
#     bash deploy/scripts/dev-up-real.sh --destroy # 连 VM 一起删
#
# 为什么需要它：macOS 上的 OrbStack / Docker Desktop / Colima 用的是裁剪内核，
# **没有 binder、也没有 SELinux**，redroid 起来约 170ms 就被 SIGHUP 打死
# （退出码 129 且 docker logs 全空）。所以真机必须跑在标准发行版内核上。
# 本脚本用 Lima 起一台 Ubuntu VM（Apple 虚拟化，arm64 原生，无转译），
# 在里面执行**与生产完全相同**的 `docker compose up -d --build` ——
# 不是另一套演示环境，就是交付形态本身。
#
# 幂等：可反复执行。VM 已存在就复用，只补齐缺失的部分。
# =============================================================================
set -euo pipefail

VM="${VM:-redroid}"
CPUS="${CPUS:-6}"
MEMORY="${MEMORY:-8GiB}"
DISK="${DISK:-40GiB}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_PORT="${WEB_PORT:-5173}"

c_ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
c_warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }
c_err()  { printf "  \033[31m✗\033[0m %s\n" "$*"; }
step()   { printf "\n\033[1m==> %s\033[0m\n" "$*"; }
die()    { c_err "$*"; exit 1; }

in_vm() { limactl shell "$VM" -- bash -c "$1"; }

[[ "$(uname -s)" == "Darwin" ]] || die "本脚本用于 macOS；Linux 宿主直接在仓库根执行 docker compose up -d --build"

# ---------------------------------------------------------------- 停止 / 销毁
if [[ "${1:-}" == "--down" ]]; then
  step "停止 VM 内的服务"
  in_vm "cd '$REPO' && sudo docker compose down" || true
  c_ok "已停止（VM 与镜像保留，下次起会很快）"
  exit 0
fi
if [[ "${1:-}" == "--destroy" ]]; then
  step "销毁 VM「${VM}」"
  limactl stop "$VM" 2>/dev/null || true
  limactl delete "$VM" 2>/dev/null || true
  c_ok "已删除。重新执行本脚本会重建（需重新拉镜像，较慢）"
  exit 0
fi

# ---------------------------------------------------------------- 前置
step "检查前置"
command -v limactl >/dev/null || die "未装 Lima。安装：brew install lima"
c_ok "limactl $(limactl --version 2>/dev/null | head -1)"

# ---------------------------------------------------------------- VM
step "准备 Ubuntu VM「${VM}」（${CPUS}C / ${MEMORY} / ${DISK}）"
if ! limactl list -q 2>/dev/null | grep -qx "$VM"; then
  c_warn "VM 不存在，正在创建（首次约 3–5 分钟）"
  # writable 挂载：compose 构建需要读仓库；写权限便于在 VM 内直接调试
  limactl start --tty=false --name="$VM" \
    --set ".vmType=\"vz\" | .cpus=${CPUS} | .memory=\"${MEMORY}\" | .disk=\"${DISK}\" |
           .mounts=[{\"location\":\"${REPO}\",\"writable\":true}]" \
    template://ubuntu
else
  c_ok "VM 已存在"
fi
if [[ "$(limactl list --format '{{.Status}}' "$VM" 2>/dev/null)" != "Running" ]]; then
  c_warn "VM 未运行，启动中"
  limactl start "$VM" >/dev/null 2>&1 || limactl start "$VM"
fi
c_ok "VM 运行中：$(in_vm '. /etc/os-release; echo "$PRETTY_NAME $(uname -r) $(uname -m)"')"

in_vm "[ -d '$REPO' ]" || die "仓库未挂载进 VM。删掉 VM 重建：bash $0 --destroy"

# ---------------------------------------------------------------- 内核门槛
step "内核门槛（真机三条硬要求）"
in_vm '
  # binder：新内核走 binderfs，老内核走 /dev/binder* 设备节点，两者认一个即可
  sudo modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null || true
  if grep -qw binder /proc/filesystems; then
    sudo mkdir -p /dev/binderfs
    mountpoint -q /dev/binderfs || sudo mount -t binder binder /dev/binderfs
  fi
' || true

BINDER_OK=$(in_vm '
  if [ -e /dev/binderfs/binder ] || [ -e /dev/binder ]; then echo yes; else echo no; fi')
if [[ "$BINDER_OK" == "yes" ]]; then
  c_ok "binder 可用：$(in_vm 'ls /dev/binderfs 2>/dev/null | tr "\n" " " || ls -d /dev/binder*')"
else
  c_err "binder 不可用。VM 内执行：sudo apt install -y linux-modules-extra-\$(uname -r) 后重试"
  die "缺 binder，真机起不来（部署手册 §2.2）"
fi

SELINUX_OK=$(in_vm '
  if [ -d /sys/fs/selinux ] || grep -q selinuxfs /proc/filesystems ||
     grep -q "^CONFIG_SECURITY_SELINUX=y" /boot/config-$(uname -r) 2>/dev/null
  then echo yes; else echo no; fi')
if [[ "$SELINUX_OK" == "yes" ]]; then
  c_ok "内核编译了 SELinux（Android init 可挂 selinuxfs）"
else
  c_warn "未检出 SELinux 支持。若实例起来后立刻退出（退出码 129 且无日志），即为此因"
fi

# ---------------------------------------------------------------- 工具链
step "VM 内工具链"
in_vm 'command -v docker >/dev/null' || {
  c_warn "装 Docker（约 1–2 分钟）"
  in_vm 'curl -fsSL https://get.docker.com | sudo sh >/dev/null 2>&1'
}
in_vm 'command -v adb >/dev/null' || {
  c_warn "装 adb"
  in_vm 'sudo apt-get update -qq && sudo apt-get install -y -qq adb'
}
in_vm "sudo usermod -aG docker \$USER" 2>/dev/null || true
c_ok "$(in_vm 'docker --version | cut -d, -f1')｜$(in_vm 'adb --version 2>/dev/null | head -1')"
in_vm 'sudo mkdir -p /data/redroid && sudo chmod 777 /data/redroid'
c_ok "实例数据目录 /data/redroid 就绪"

# ---------------------------------------------------------------- 出网代理
# 国内网络下 DNS 常被污染：registry-1.docker.io 会被解析到 Facebook/Dropbox/Twitter
# 的地址段（69.63.x / 108.160.x / 157.240.x / 199.59.x），表现为 TCP 能连、TLS 超时。
# 若 Mac 上有可用代理，就把它透给 VM 里的 docker daemon（VM 经 host.lima.internal 访问 Mac）。
step "VM 内 Docker 出网"
PROXY="${PROXY:-${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-}}}}}"
if [[ -n "$PROXY" ]]; then
  PROXY_PORT="${PROXY##*:}"; PROXY_PORT="${PROXY_PORT%%/*}"
  [[ "$PROXY_PORT" =~ ^[0-9]+$ ]] || die "无法从 PROXY=$PROXY 解析端口"
  SSHCFG="$HOME/.lima/${VM}/ssh.config"
  [[ -f "$SSHCFG" ]] || die "找不到 $SSHCFG"

  # 必须用 **SSH 反向隧道**，不能让 VM 直连 host.lima.internal：
  # Lima 的用户态网关会接受到网关地址的 TCP 握手（看起来"可达"），却转发不到 Mac 的
  # 127.0.0.1，实际表现是 docker 报 `proxyconnect tcp: dial tcp 192.168.5.2:7897: i/o timeout`。
  # 反向隧道把 Mac 的 127.0.0.1:<port> 直接映到 VM 的 127.0.0.1:<port>，稳定可用。
  pkill -f "R ${PROXY_PORT}:127.0.0.1:${PROXY_PORT}" 2>/dev/null || true
  ssh -F "$SSHCFG" -f -N -o ExitOnForwardFailure=yes \
      -R "${PROXY_PORT}:127.0.0.1:${PROXY_PORT}" "lima-${VM}" \
    || die "反向隧道建立失败（Mac 上 127.0.0.1:${PROXY_PORT} 有在监听吗？）"
  c_ok "反向隧道就绪：VM:127.0.0.1:${PROXY_PORT} → Mac:127.0.0.1:${PROXY_PORT}"

  in_vm "
    sudo mkdir -p /etc/systemd/system/docker.service.d
    printf '[Service]\nEnvironment=\"HTTP_PROXY=http://127.0.0.1:${PROXY_PORT}\"\nEnvironment=\"HTTPS_PROXY=http://127.0.0.1:${PROXY_PORT}\"\nEnvironment=\"NO_PROXY=localhost,127.0.0.1,::1\"\n' \
      | sudo tee /etc/systemd/system/docker.service.d/proxy.conf >/dev/null
    sudo systemctl daemon-reload && sudo systemctl restart docker
  "
  c_ok "VM 内 docker 已配置走该代理"
else
  c_warn "未检测到代理（未设 http_proxy/https_proxy）。国内网络若拉不动镜像，"
  c_warn "  用 PROXY=http://127.0.0.1:7897 bash ${0} 重跑，或在 VM 内配镜像加速器（部署手册 §3.2）"
fi

# ---------------------------------------------------------------- redroid 镜像
step "redroid 镜像"
IMG="${CLOUD_REDROID_IMAGE:-redroid/redroid:12.0.0_64only-latest}"
if in_vm "sudo docker image inspect '$IMG' >/dev/null 2>&1"; then
  c_ok "$IMG 已在 VM 内"
else
  c_warn "拉取 ${IMG}（约 2 GB，首次较慢）"
  in_vm "sudo docker pull '$IMG'" || die "拉取失败。国内网络请先配镜像加速器（部署手册 §3.2）"
fi

# ---------------------------------------------------------------- 起栈
step "在 VM 内起栈（与生产完全相同的 compose）"
in_vm "cd '$REPO' && sudo docker compose up -d --build --wait" \
  || die "起栈失败。VM 内看日志：limactl shell $VM -- sudo docker compose -f '$REPO/docker-compose.yml' logs"
in_vm "cd '$REPO' && sudo docker compose ps --format 'table {{.Name}}\t{{.Status}}'" | sed 's/^/  /'

# ---------------------------------------------------------------- 端口转发
# Lima 的自动端口转发对 docker 发布的 0.0.0.0 端口并不总是生效（实测 5173 没转过来），
# 所以显式建 SSH 正向隧道，保证 Mac 上 http://localhost:5173 一定能开。
step "端口转发到 Mac"
SSHCFG="${SSHCFG:-$HOME/.lima/${VM}/ssh.config}"
for P in "$WEB_PORT" 8000; do
  pkill -f "L ${P}:127.0.0.1:${P}" 2>/dev/null || true
  if ssh -F "$SSHCFG" -f -N -o ExitOnForwardFailure=yes \
         -L "${P}:127.0.0.1:${P}" "lima-${VM}" 2>/dev/null; then
    c_ok "Mac:${P} → VM:${P}"
  else
    c_warn "Mac:${P} 转发失败（该端口可能已被占用），可直接访问 VM 地址"
  fi
done

# ---------------------------------------------------------------- 访问
step "完成"
cat <<EOF
  管理控制台：http://localhost:${WEB_PORT}   （admin / admin123）
      经上面的 SSH 隧道访问。隧道断了就重跑本脚本；也可直连 VM：
      http://$(in_vm "hostname -I | awk '{print \$1}'"):${WEB_PORT}

  这里的「建机」= VM 内真实 docker run redroid，「多画面预览」= 真机 adb 截图。
  排障入口：管理端左侧「系统自检」。

  常用：
      bash $0 --down       停服务（保留 VM 与镜像，下次秒起）
      bash $0 --destroy    连 VM 一起删
      limactl shell $VM    进 VM
EOF
