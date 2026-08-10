# 部署说明 —— X86 云手机平台 Demo

本目录是**部署层**：Docker 编排 + Redroid 实例脚本 + STF 群控 + 宿主机准备 + iOS 皮肤流程。
后端（FastAPI）与前端（Vue）源码分别在 `../backend`、`../frontend`，本层不改它们的业务代码。

平台支持两种设备后端（由 `CLOUD_DEVICE_BACKEND` 切换）：

- **redroid（默认）**：真实 Android 实例，与生产交付一致；需宿主内核满足 binder + SELinux + cgroup（部署手册 §2.2/§2.2b）
- **simulator（降级）**：无需 Docker/内核模块/adb，任意平台（macOS/Windows/Linux）即可跑通
  §1 主流程闭环的全部 8 条验收。**仅用于无真机环境下的功能验证，不要拿去给甲方演示**。

---

## 端口约定（全栈自洽）

| 服务 | 端口 | 说明 |
|---|---|---|
| 后端 backend | **8000** | uvicorn，API 前缀 `/api`，WebSocket `/api/ws`，健康 `/api/health` |
| 前端 frontend | **5173**（宿主）→ 80（容器 nginx） | nginx 反代 `/api`、`/api/ws` 到 backend:8000 |
| PostgreSQL | **5432** | 主库，账号库名均为 `cloud` |
| Redis | **6379** | 预留（会话/广播/批量队列位） |
| Redroid 实例 | **5555 + device_id** | 与后端一致：容器 `redroid_{id}`，宿主端口 5555+id |
| STF Web | **7100** | 群控后台 |
| STF provider | 7400–7500 | 投屏/控制端口段 |
| RethinkDB | **8080 / 28015** | STF 的库（Web / 驱动） |

---

## 场景 A：一键起整套（默认即真机）

一条命令拉起 postgres + redis + backend + frontend：

```bash
cd ..                       # 到仓库根目录（docker-compose.yml 所在）
docker compose up -d --build

# 打开：
#   前端管理系统   http://localhost:5173
#   后端 API 文档  http://localhost:8000/docs
#   初始管理员     admin / admin123
```

说明：
- 后端默认 `CLOUD_DEVICE_BACKEND=redroid`（真机）；无真机条件时用 docker-compose.simulator.yml 降级。
- 数据库自动指向 compose 内的 postgres（`postgresql+asyncpg://cloud:cloud@postgres:5432/cloud`）。
- 前端由 nginx 托管并反代 `/api`、`/api/ws`，前后端同源，无需额外 CORS 配置。

> 注：`../frontend` 需存在标准 Vite 工程（`package.json` + `npm run build` 产出 `dist/`）。
> 若前端源码尚未落地，可先只起后端做 API 联调：`docker compose up -d --build postgres redis backend`。

停止 / 清库：

```bash
docker compose down          # 停服务，保留数据卷
docker compose down -v       # 连同 postgres/redis 数据卷一起删
```

---

## 场景 B：真实 Redroid（Linux 宿主机）

### B1. 宿主机就绪（PoC D2）

```bash
cd deploy/scripts
chmod +x host-setup.sh
sudo ./host-setup.sh         # 装 binder/ashmem 内核模块 + docker + adb + scrcpy，并校验
```

### B2. 起云手机实例（PoC D3/D9，一机一码）

```bash
cd deploy/redroid
chmod +x start-instance.sh batch-start.sh

# 单台（Intel/AMD 核显用 --gpu-mode host；NVIDIA/无核显用 guest）
./start-instance.sh --id 0 --model "Pixel 6" --brand google --width 720 --height 1280 --dpi 320
scrcpy -s localhost:5555     # 看画面

# 批量起 10 台（端口/数据目录/机型各自独立）
./batch-start.sh -n 10
```

### B3.（可选）套 iOS 皮肤（D2）

见 `deploy/ios-skin/README.md`：对目标实例 `adb install` Lawnchair fork + 图标包 + 壁纸。

### B4. 群控投屏（PoC D6/D7）

```bash
cd deploy/stf
# 先让宿主连上要纳管的实例
for p in 5555 5556 5557; do adb connect localhost:$p; done
adb devices
# 拉起 STF + RethinkDB（host 网络共享宿主 adb server）
HOST_IP=$(hostname -I | awk '{print $1}') docker compose -f docker-compose.stf.yml up -d
echo "打开 http://$HOST_IP:7100"
```

### B5. 把后端切到 redroid

两种方式，任选其一：

**方式一：后端直接跑在宿主机（推荐，最稳）**
```bash
cd backend
export CLOUD_DEVICE_BACKEND=redroid
export CLOUD_REDROID_GPU_MODE=host          # Intel/AMD 核显；NVIDIA 用 guest
export CLOUD_REDROID_DATA_DIR=/data/redroid
export CLOUD_DATABASE_URL=postgresql+asyncpg://cloud:cloud@localhost:5432/cloud
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
后端会用 Docker SDK 起 `redroid_{id}` 容器（宿主端口 5555+id），并用 adb 下发操控。

**方式二：后端在 compose 容器内（默认，无需任何改动）**
根目录 `docker compose up -d --build` 默认就是 redroid，已挂好 `/var/run/docker.sock` 与
`/data/redroid`，并用 `CLOUD_REDROID_ADB_MODE=container` 经容器名连 adb ——
**刻意不用 `network_mode: host`**，那会让 nginx 的 `proxy_pass backend:8000` 解析不到而整栈断掉。

### B6. 密度压测（PoC D10 / 计划 D19）

```bash
cd deploy/scripts
chmod +x density-test.sh
./density-test.sh -n 20 --gpu-mode host     # 起 20 台 720p，打印 docker stats + free -h
./density-test.sh --cleanup                 # 压测后清理
```

---

## 目录结构

```
deploy/
├── README.md                     # 本文
├── nginx/
│   └── default.conf              # 前端 nginx 反代 /api、/api/ws -> backend:8000
├── redroid/
│   ├── props-template.env        # 一机一码 props 模板（机型/序列号/分辨率/GPU/代理）
│   ├── start-instance.sh         # 起单台实例（props 注入 + adb connect，对齐后端）
│   └── batch-start.sh            # 批量起 N 台（端口/数据目录/机型各异）
├── stf/
│   └── docker-compose.stf.yml    # STF/DeviceFarmer + RethinkDB，纳管 redroid
├── scripts/
│   ├── host-setup.sh             # Ubuntu 宿主就绪：内核模块 + docker + adb + scrcpy
│   ├── dev-up-real.sh            # macOS 一键起真机（Lima Ubuntu VM 内跑生产同款 compose）
│   └── density-test.sh           # 批量 20 台 720p，docker stats + free -h
└── ios-skin/
    └── README.md                 # iOS 皮肤应用流程（Lawnchair fork + 图标 + 壁纸 + Dock）

# 另外（在各自目录，供 compose 构建）：
../docker-compose.yml             # 整套 demo 栈（postgres/redis/backend/frontend）
../backend/Dockerfile             # 后端镜像（python:3.12-slim + uvicorn:8000）
../frontend/Dockerfile            # 前端镜像（node:22 + pnpm 构建 -> nginx:alpine 托管）
```

---

## 验收清单映射（§5「主流程跑通」8 条 → 本层支撑点）

| # | 验收项 | 由什么支撑 |
|---|---|---|
| 1 | 登录 | backend 鉴权 + frontend（compose 场景 A 一键起） |
| 2 | 建机（显示 iOS 皮肤） | `redroid/start-instance.sh` / `batch-start.sh` + `ios-skin/README.md` |
| 3 | 开网页 | 实例内 Chromium/WebView（start-instance 末尾 `am start VIEW` 已验证路径） |
| 4 | 独立身份（标识/IP/指纹各异） | `props-template.env` + 后端 `fingerprint.py` 注入；`--proxy` 独立出口 |
| 5 | 投屏预览（Web & PC 多画面） | `stf/docker-compose.stf.yml`（minicap）+ 后端 WS `/api/ws` 预览帧 |
| 6 | 单台操控 | STF minitouch + 后端 `/api/devices/{id}/control/*` |
| 7 | 批量同步（1 控 N） | 后端 `/api/batch/*` + `batch-start.sh` 起的多实例 |
| 8 | App 端 + 脚本 | 复用后端 API；脚本引擎见计划 D13（Airtest，PoC D8） |

> 说明：默认的 redroid 后端跑的就是真实安卓，画面为 `adb screencap` 真机截图；
> simulator 是无真机环境下的降级（渲染帧），链路一致但**不可用于演示**。
