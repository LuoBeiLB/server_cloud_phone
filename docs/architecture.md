# 架构说明

## 分层

```
┌─────────────────────────────────────────────────────────────┐
│  接入端                                                       │
│  Web 控制台(Vue)   PC 客户端(Electron)   App 客户端(Kotlin)   │
└───────────────┬───────────────┬───────────────┬─────────────┘
                │ REST /api      │ 同一套 API     │
                │ WS   /api/ws   │               │
┌───────────────▼───────────────────────────────▼─────────────┐
│  平台后端 (FastAPI)                                           │
│  鉴权(JWT) · 设备/分组 CRUD · 一机一码 · 单机操控 · 批量 ·    │
│  脚本录制回放 · WebSocket(状态/进度/预览帧广播)               │
└───────────────┬─────────────────────────────────────────────┘
                │ DeviceBackend 抽象（可插拔）
        ┌───────┴────────┐
        ▼                ▼
  SimulatorBackend   RedroidBackend
  (内存态+SVG预览)    (Docker + Redroid + adb + minicap/minitouch)
        │                │
        ▼                ▼
   任意平台           Linux 宿主机
   (演示/开发)        (真实 x86 安卓实例)
```

关键设计：上层只依赖 `orchestrator/base.py` 的 `DeviceBackend` 抽象。切换真实/模拟只改一个
环境变量 `CLOUD_DEVICE_BACKEND`，其余代码零改动。这让 demo 能在 macOS 上先跑通业务闭环，
再无缝迁到 Linux 上换成真实 Redroid。

## 数据流

- **建机**：`POST /devices/batch` → `services.create_device` 生成一机一码(`fingerprint.py`) → `backend.create/start` → 落库 → WS 广播 `device_status`。
- **预览**：前端 WS 发 `subscribe{device_ids,fps}` → 后端 `routers/ws.py` 周期性 `backend.screenshot()` 渲染帧 → 推 `preview`。simulator 渲染 SVG(`preview.py`)，redroid 用 `adb exec-out screencap`（生产替换为 minicap/scrcpy 低延迟流）。
- **批量/同步**：`POST /batch/*` → 并发对选中设备执行 → 每台完成推 `batch_progress`。同步操控做了跨分辨率坐标折算(`batch._scale`)。
- **脚本**：录制在前端把单机操作序列收集为 `steps`；`POST /scripts/{id}/run` 把步骤在多台设备上并发回放，产出逐设备逐步骤报告。

## 一机一码（fingerprint.py）

每台设备用一个稳定 seed 派生三组互不相同的字段，重启保持一致、设备间互不相同：

- **设备标识**：brand/manufacturer/model/android_id/serialno/imei/mac —— 作为 Redroid 启动 props 注入（`redroid_props()`）。
- **浏览器指纹**：UA/分辨率/DPI/DPR/时区/语言/WebGL vendor+renderer/Canvas 噪声种子/硬件并发/内存 —— 注入 Chromium。
- **网络**：独立出口 IP + 代理位（从 `CLOUD_PROXY_POOL` 分配）。

对应验收「抽查 3 台，设备标识/出口 IP/浏览器指纹各不相同」。

## 真实 Redroid 落地要点（来自方案包，避坑）

1. **GPU**：硬件渲染走 Intel/AMD 的 Mesa `/dev/dri/render*`（`gpu_mode=host`）。**NVIDIA 闭源驱动不支持此路径**，只能软件渲染(guest)或 QEMU+virtio-gpu（性能损耗大）。硬件选型据此定，别照抄 8×L40S。
2. **内核模块**：Redroid 依赖 `binder_linux`，这是硬前提，过不去要换发行版内核（见 `deploy/scripts/host-setup.sh`）。
3. **STF 纳管**：STF 原为 USB 物理机设计，接 redroid 需让 provider 走 `adb connect ip:5555` 的 TCP 纳管（`deploy/stf/`）。
4. **投屏低延迟**：demo 用截图轮询；生产换 minicap / ws-scrcpy(H.264 over WebSocket)。
5. **一机一码深度**：prop 能改机型/序列号/AndroidID；IMEI 与更深改机需 Magisk/LSPosed 模块，属长期运维项。
6. **ARM 转译授权**：libndk/libhoudini 为专有库，规模化商用需书面确认授权责任（合规边界）。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI · SQLAlchemy(async) · aiosqlite/asyncpg · PyJWT · WebSocket |
| 前端 | Vue3 · Vite · Element Plus · Pinia · vue-router · axios |
| 云手机 | Redroid(Docker) · Chromium · Lawnchair(iOS 皮肤) |
| 群控 | STF/DeviceFarmer · minicap · minitouch · adbkit |
| 脚本 | Airtest + Poco（步骤模型已抽象，后端可直连 Airtest 运行时）|
| PC 端 | Electron |
| App 端 | Kotlin + Jetpack Compose + Retrofit |
| 编排 | Docker Compose（demo 规模）· k8s（规模化留后续）|
