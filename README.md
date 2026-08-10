# X86 云手机平台 · 主流程 Demo

依据《X86云手机平台_本月Demo详细计划_主流程跑通.md》实现的可运行 demo：
**x86 虚拟云手机 + 苹果 UI + 群控投屏 + App 客户端 + 网站登录及管理系统，类魔云腾**。

本仓库把甲方五要素做成端到端能演示的一条闭环，并且**在没有 Docker/Redroid 的机器上也能直接跑通**
（simulator 后端），迁到 Linux 宿主机再切 redroid 后端即为真实云手机。

```
登录 Web 管理系统 → 批量建 N 台云手机（iOS 皮肤）→ 每台浏览器开网页
→ 每台独立设备标识/出口 IP/浏览器指纹 → Web & PC 多画面预览 + 单台实时操控
→ 一键全部开同一网页 / 同步操控（1 控 N）→ App 端看设备并操控 → 录脚本跨设备回放
```

## 目录结构

| 目录 | 内容 | 甲方要素 |
|---|---|---|
| `backend/` | FastAPI + WebSocket，设备编排/鉴权/一机一码/批量/脚本；后端可插拔（simulator ↔ redroid） | 平台底座 |
| `frontend/` | Vue3 + Element Plus 管理控制台（登录/设备/多画面/批量/脚本） | 网站管理系统 + Web 群控 |
| `deploy/` | docker-compose、Redroid 启动脚本、STF 集成、宿主机准备、密度压测、iOS 皮肤流程 | x86 云手机 + 苹果 UI |
| `pc-client/` | Electron 封装 Web 端出 Windows 客户端（对齐魔云腾） | PC 群控客户端 |
| `app-client/` | 安卓 App（Kotlin+Compose）：登录/设备列表/投屏/批量 | App 客户端 |
| `docs/` | 架构说明 + 逐日计划映射 | — |

## 5 分钟跑通（simulator，macOS/Windows/Linux 通用，无需 Docker）

```bash
# 1) 后端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" aiosqlite pydantic pydantic-settings PyJWT python-multipart httpx
uvicorn app.main:app --reload            # http://localhost:8000/docs

# 2) 前端（另开终端；用 pnpm，仓库锁文件是 pnpm-lock.yaml。Node 需 ≥ 22.13）
cd frontend && corepack enable && pnpm install && pnpm run dev # http://localhost:5173  登录 admin/admin123

# 3) 一键验证 8 条验收（后端已启动的前提下）
cd backend && source .venv/bin/activate && python -m tests.smoke
```

`tests/smoke.py` 会自动跑完登录→建 10 台→抽查指纹→预览→单机操控→批量同步→分组→脚本回放，全绿即主流程跑通。

> ⚠️ `tests/smoke.py` 会**批量创建 10 台设备**，只适合 simulator。真机（redroid）环境请用
> **非破坏性**的 `python acceptance_live.py`：不建机不删机、只用现有在跑的设备核验，
> 跑完还原设备原来打开的网页；并会检出「有画面但设备其实已失联」的伪装情况。

## 一条命令起整套（Docker Compose）

```bash
bash deploy/scripts/up.sh             # 起栈并**打印所有访问地址**（推荐）
# 或者直接：docker compose up -d --build
```

起完后的访问地址（把 `<服务器IP>` 换成实际地址，脚本会自动打印）：

| 服务 | 地址 |
|---|---|
| **管理控制台** | `http://<服务器IP>:5173`　账号 `admin` / `admin123` |
| **系统自检**（排障先看这里） | `http://<服务器IP>:5173/#/diagnostics` |
| 后端 API 文档 | `http://<服务器IP>:8000/docs` |
| 健康探针（免登录） | `http://<服务器IP>:8000/api/health` |

随时用 `bash deploy/scripts/up.sh --urls` 重新打印这些地址。

> 🩺 **出问题先开「系统自检」**（左侧菜单，或 `/#/diagnostics`）。它逐项实测数据库、Docker、
> redroid 镜像、内核 binder、`/dev/dri`、adb、磁盘、内存、以及「库里说在跑但容器已经没了」
> 的设备，并**直接给出该敲的命令**。连自检页都打不开时用免鉴权探针：
> `curl -s --noproxy '*' http://localhost:5173/api/health`。
> 设计见[技术文档 §12.5 故障可见性](docs/技术文档.md)，排障步骤见[部署手册第 11 章](docs/部署搭建手册_x86服务器.md)。

> ⚠️ 上面这条命令起的**就是真机**（Redroid），与生产交付形态完全一致 ——
> 不分「演示版 / 真机版」。前提是宿主内核满足 ⛔ 三条硬门槛：
> ① binder（`/dev/binderfs/binder` 或 `/dev/binder*`）；② **SELinux**
> （`/sys/fs/selinux`、`/proc/filesystems` 有 selinuxfs、或 `CONFIG_SECURITY_SELINUX=y`）；
> ③ cgroup v1 层级。三条都在「系统自检」里，缺什么会直接告诉你怎么办。
>
> 首次需先 `docker pull redroid/redroid:12.0.0_64only-latest`。

## macOS 开发机上跑真机

macOS 的 OrbStack / Docker Desktop **跑不了真机**（裁剪内核没有 SELinux，实例会以退出码 129
立刻死且无任何日志），但 **Lima + Ubuntu 可以**（已实测：Android 12 / SDK 31 / arm64-v8a）：

```bash
bash deploy/scripts/dev-up-real.sh                      # 一键：建 VM → 起真机栈 → 转发端口
PROXY=http://127.0.0.1:7897 bash deploy/scripts/dev-up-real.sh   # 国内网络加代理
```

脚本在 Ubuntu VM 里执行的就是上面那条生产同款 compose 命令，完成后开 http://localhost:5173。

## 实在没有真机条件时（降级）

```bash
docker compose -f docker-compose.yml -f docker-compose.simulator.yml up -d --build
```

模拟设备渲染 SVG 画面、不执行 adb，**只用于无真机环境下的功能验证，不要拿去给甲方演示**。

## 切换到真实 Redroid（Linux 宿主机，后端裸装）

```bash
sudo bash deploy/scripts/host-setup.sh        # binder 内核模块 + docker + adb（PoC D2）
export CLOUD_DEVICE_BACKEND=redroid
export CLOUD_REDROID_GPU_MODE=host            # Intel/AMD 核显；NVIDIA 用 guest（见下）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> ⚠️ 关键坑（来自方案包）：Redroid 硬件渲染走 Intel/AMD 的 Mesa `/dev/dri` 路径，
> **NVIDIA 闭源驱动不支持此路径**——别照抄甲方的 8×L40S 做渲染。详见 `docs/architecture.md`。

## 文档导航

| 文档 | 内容 |
|---|---|
| **[`STATUS.md`](STATUS.md)** | **进度跟踪**：验收进度、与目标差距、已实现/待办、当前运行态（先看这个）|
| **[`docs/部署搭建手册_x86服务器.md`](docs/部署搭建手册_x86服务器.md)** | **交付部署首选**：x86 服务器选型红线（核显/NVIDIA/ARM 转译）、内核 binder、国内镜像加速与离线部署、三条部署路径、生产加固、FAQ |
| `docs/X86云手机平台_项目交付说明书_v1.1.docx` | 甲方交付说明书（Word）：技术方案 · 功能清单 · 实现进度 |
| **[`docs/技术文档.md`](docs/技术文档.md)** | **完整技术手册**（新人从此上手）：项目概述、系统架构、技术栈、目录结构、快速开始、完整 API 参考、一机一码、设备编排、实时预览与操控、部署、真机实测、计划验收、排障 FAQ、合规边界 |
| [`docs/architecture.md`](docs/architecture.md) | 架构分层图与数据流速览 |
| [`docs/plan-mapping.md`](docs/plan-mapping.md) | 8 条验收清单 + D1–D20 逐日任务映射 |
| [`docs/验收报告.md`](docs/验收报告.md) | **交付验收报告**：8 条验收逐条判据+证据 + 已实现/待实现清单 |
| [`docs/扩展功能.md`](docs/扩展功能.md) | 扩展模块：看板/告警/任务/详情/报表/日志/RBAC/应用/分组/投屏/CP-007 |
| [`docs/架构图.md`](docs/架构图.md) | 系统架构图 + 真机部署拓扑（mermaid） |
| [`docs/演示脚本.md`](docs/演示脚本.md) | 演示彩排逐步脚本（D18/D20） |
| [`docs/三端联调.md`](docs/三端联调.md) | Web/PC/App 三端连同一后端 runbook |
| [`docs/规模化方案.md`](docs/规模化方案.md) | 500 台规模化 k8s 预研（架构/容量估算/BOM/迁移路径）|
| [`docs/redroid-real-benchmark.md`](docs/redroid-real-benchmark.md) | 真实 Redroid Android 实测报告 |

## 与计划的对应

- 8 条验收清单 → 见 `docs/plan-mapping.md` 的「验收对照」。
- D1–D20 逐日任务 → 见 `docs/plan-mapping.md` 的「逐日映射」，标注每日产物落在哪个文件。

## 合规边界

本仓库交付的是**云手机群控平台技术底座**（等同魔云腾/河马等商用产品形态）。设备指纹隔离、独立 IP 属平台通用能力；
目标网站的账号合规、反作弊对抗、业务合法性由使用方承担。ARM 转译库（libndk/libhoudini）商用授权需另行确认。
"# server_cloud_phone" 
