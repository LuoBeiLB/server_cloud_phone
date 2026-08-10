"""平台配置。所有可调项集中在此，通过环境变量或 .env 覆盖。"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLOUD_", extra="ignore")

    # --- 基础 ---
    app_name: str = "X86 云手机平台"
    api_prefix: str = "/api"
    debug: bool = True

    # --- 数据库 ---
    # dev 默认 SQLite（零依赖）；生产改为 postgresql+asyncpg://user:pass@host/db
    database_url: str = "sqlite+aiosqlite:///./cloud_platform.db"

    # --- 鉴权（JWT）---
    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # --- 初始管理员（首启动自动播种）---
    admin_username: str = "admin"
    admin_password: str = "admin123"

    # --- 设备编排后端 ---
    # simulator：无需 Docker，可在任意平台跑 demo（macOS/Windows/Linux）
    # redroid：真实 Docker + Redroid，仅 Linux 宿主机
    device_backend: Literal["simulator", "redroid"] = "simulator"

    # Redroid 后端参数（device_backend=redroid 时生效）
    redroid_image: str = "redroid/redroid:12.0.0_64only-latest"
    redroid_data_dir: str = "/data/redroid"
    redroid_base_adb_port: int = 5555
    redroid_gpu_mode: str = "guest"  # host=宿主 GPU 加速(Intel/AMD)，guest=软件渲染

    # adb 连接方式：
    #   port      —— adb connect localhost:(base+id)，走宿主发布端口。
    #                后端必须与 redroid 容器共享网络命名空间（后端跑宿主机，
    #                或容器加 network_mode: host）。
    #   container —— adb connect redroid_<id>:5555，走 docker 网络内的容器名。
    #                后端可以正常跑在 compose 里，**不需要 network_mode: host**。
    # 为什么需要 container 模式：host 网络下的后端不在 compose 桥接网上，
    # 前端 nginx 的 proxy_pass backend:8000 会解析不到，整个栈就断了。
    redroid_adb_mode: Literal["port", "container"] = "port"
    # container 模式下把 redroid 容器接入的 docker 网络（通常是 compose 的默认网络）
    redroid_network: str = ""

    # --- scrcpy 低延迟投屏（ws-scrcpy）---
    # 留空 = 未部署，前端「scrcpy 投屏」按钮会置灰并说明原因。
    #
    # 之前这里是前端写死的 `http://<当前域名>:8100`，而 docker-compose 里**从来没有**
    # ws-scrcpy 服务 —— 一键部署起不来它，点按钮只会打开一个不存在的地址（或误开
    # 宿主上恰好占用 8100 的别的服务）。ws-scrcpy 依赖树老、构建重，不适合塞进
    # 一键栈，所以改为「显式配置才启用」：部署了就填地址，没部署就诚实置灰。
    # 例：CLOUD_WS_SCRCPY_BASE=http://10.0.0.5:8100
    ws_scrcpy_base: str = ""

    # --- 网络/代理位（一机一码：独立出口 IP）---
    # 代理池，形如 ["socks5://1.2.3.4:1080", "http://5.6.7.8:8080"]
    proxy_pool: list[str] = []

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173", "*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
