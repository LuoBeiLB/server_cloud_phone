"""FastAPI 应用入口。

启动：uvicorn app.main:app --reload  （在 backend/ 目录下）
文档：http://localhost:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import settings
from .database import init_db
from .orchestrator.base import DeviceCommandError, DeviceProvisionError, DeviceUnreachable
from .routers import (
    alerts,
    apps,
    audit,
    auth,
    batch,
    control,
    device_detail,
    devices,
    diagnostics,
    files,
    groups,
    logs,
    metrics,
    reports,
    scripts,
    skin,
    tasks,
    users,
    ws,
)
from .seed import seed
from .ws_manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from .routers.tasks import scheduler_loop

    await init_db()
    await seed()
    # 启动定时任务调度器（后台协程）
    asyncio.create_task(scheduler_loop())
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(DeviceUnreachable)
async def _device_unreachable_handler(request: Request, exc: DeviceUnreachable) -> JSONResponse:
    """设备控制通道不可用 → 503，并带上排障线索。

    宁可让调用方看到明确的失败，也不返回一张「看着正常」的皮肤图/假成功。
    """
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "device_id": exc.device_id,
            "serial": exc.serial,
            "unreachable": True,
            "hint": f"设备失联。检查容器是否在跑，并执行 adb connect {exc.serial}",
        },
    )


@app.exception_handler(DeviceProvisionError)
async def _device_provision_error_handler(
    request: Request, exc: DeviceProvisionError
) -> JSONResponse:
    """云手机拉不起来 → 502，带上「卡在哪一步 + 原因 + 处置 + 实测证据」。

    甲方是「一键 docker」跑起来的，看不到宿主机日志。这里必须把 docker logs 里
    的关键信息（容器状态/退出码/OOM/日志尾部）一并回传，否则界面上只有一句
    「启动失败」，等于没有提示。
    """
    return JSONResponse(
        status_code=502,
        content={
            "detail": str(exc),
            "provision_failed": True,
            **exc.as_dict(),
        },
    )


@app.exception_handler(DeviceCommandError)
async def _device_command_error_handler(request: Request, exc: DeviceCommandError) -> JSONResponse:
    """设备命令失败（路径不存在 / 无权限等）→ 502，带上原始报错。

    同样禁止静默返回空结果：「读不到」必须和「本来就没有」区分开。
    """
    return JSONResponse(
        status_code=502,
        content={
            "detail": str(exc),
            "device_id": exc.device_id,
            "what": exc.what,
            "command_failed": True,
        },
    )


api = settings.api_prefix
app.include_router(auth.router, prefix=api)
app.include_router(groups.router, prefix=api)
app.include_router(devices.router, prefix=api)
app.include_router(control.router, prefix=api)
app.include_router(batch.router, prefix=api)
app.include_router(scripts.router, prefix=api)
app.include_router(metrics.router, prefix=api)
app.include_router(alerts.router, prefix=api)
app.include_router(tasks.router, prefix=api)
app.include_router(device_detail.router, prefix=api)
app.include_router(reports.router, prefix=api)
app.include_router(logs.router, prefix=api)
app.include_router(files.router, prefix=api)
app.include_router(users.router, prefix=api)
app.include_router(audit.router, prefix=api)
app.include_router(apps.router, prefix=api)
app.include_router(skin.router, prefix=api)
app.include_router(diagnostics.router, prefix=api)
app.include_router(ws.router, prefix=api)


@app.get("/")
async def root() -> dict:
    return {
        "name": settings.app_name,
        "backend": settings.device_backend,
        "docs": "/docs",
        "ws_clients": manager.count,
    }


@app.get(f"{api}/health")
async def health() -> dict:
    """免鉴权的轻量就绪探针（compose healthcheck 用的就是它）。

    这里刻意只回布尔量、不回主机细节 —— 详细自检在 /api/diagnostics（需登录）。
    但数据库状态必须放进来：库挂了 → seed/登录都失败 → 甲方根本进不去自检页，
    此时这个免鉴权端点是唯一能告诉他「问题在数据库」的地方。
    """
    db_ok, db_err = True, ""
    try:
        from .database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        db_ok, db_err = False, f"{e.__class__.__name__}"

    body: dict = {
        "status": "ok" if db_ok else "degraded",
        "backend": settings.device_backend,
        "database": "ok" if db_ok else "fail",
        # 前端据此决定「scrcpy 投屏」按钮是否可用（空 = 未部署 ws-scrcpy）
        "ws_scrcpy_base": settings.ws_scrcpy_base,
    }
    if not db_ok:
        body["detail"] = f"数据库不可用（{db_err}）"
        body["hint"] = "docker compose ps 看 postgres 是否 healthy；详细自检见 /api/diagnostics"
    return body
