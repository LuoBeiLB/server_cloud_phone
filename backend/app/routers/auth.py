"""登录鉴权（demo 验收 §1：账号密码登录）。"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_access_token, get_current_user, verify_password
from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# —— 登录限流（防暴力破解）——
# 规则：同一「IP + 用户名」组合连续失败 5 次，锁定该组合 10 分钟；登录成功清零。
# 按组合锁定而非全局锁定：攻击者试错被锁只影响他自己的 IP 登那个账号，
# 其他用户、以及他自己登别的账号都不受影响。
MAX_FAILS = 5
LOCK_SECONDS = 600
_failures: dict[tuple[str, str], list] = {}  # (ip, username) -> [失败次数, 锁定到期时间戳]

# —— 登录串行锁 ——
# 同一「IP + 用户名」的登录尝试必须排队挨个处理：检查锁 → 验证密码 → 记失败/清零
# 是一个不可分割的整体。不加这把锁时，并发请求会「插队」：正确密码的请求在锁生成前
# 通过检查、在锁生成后才完成验证并顺手把锁清零，锁定形同虚设（已实测复现）。
_login_guards: dict[tuple[str, str], asyncio.Lock] = {}

print("=" * 30, "AUTH RATE-LIMIT V3 LOADED", "=" * 30, flush=True)


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。

    生产环境前端 nginx（docker-compose 的 frontend 容器）反代 /api 到后端，
    request.client.host 会是 nginx 的内网 IP——若直接用它计数，所有用户共用一个
    计数器，一人试错全员被锁。nginx 已透传 X-Forwarded-For，优先取第一个。
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_lock(key: tuple[str, str]) -> None:
    """锁定中的组合直接拒绝，连密码都不验证。"""
    _, locked_until = _failures.get(key, [0, 0])
    if locked_until > time.time():
        remain = int(locked_until - time.time()) // 60 + 1
        print(f"[login-lock] {key} 锁定中，拒绝本次登录（剩余 {remain} 分钟）", flush=True)
        raise HTTPException(status_code=429, detail=f"尝试次数过多，请 {remain} 分钟后再试")


def _record_fail(key: tuple[str, str]) -> None:
    # 顺带清理已过期的锁定记录，避免字典无限增长
    now = time.time()
    for k in [k for k, v in _failures.items() if v[1] and v[1] <= now]:
        _failures[k] = [0, 0]
    fails, _ = _failures.get(key, [0, 0])
    fails += 1
    locked_until = now + LOCK_SECONDS if fails >= MAX_FAILS else 0
    _failures[key] = [fails, locked_until]


def _clear_fails(key: tuple[str, str]) -> None:
    _failures.pop(key, None)


def _guard_for(key: tuple[str, str]) -> asyncio.Lock:
    guard = _login_guards.get(key)
    if guard is None:
        guard = asyncio.Lock()
        _login_guards[key] = guard
    # 极端情况下（大量不同 IP+账号组合）防字典无限增长：只删没被占用的锁
    if len(_login_guards) > 10000:
        for k, g in list(_login_guards.items()):
            if not g.locked():
                _login_guards.pop(k, None)
    return guard


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    key = (_client_ip(request), body.username)
    async with _guard_for(key):
        _check_lock(key)
        user = (
            await db.execute(select(User).where(User.username == body.username))
        ).scalar_one_or_none()
        if user is None or not verify_password(body.password, user.password_hash):
            _record_fail(key)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        # 持锁期间本组合不会有新失败进来，这次复查是双保险：
        # 防未来有人改动代码破坏「检查-验证-记录」的串行假设。
        _check_lock(key)
        _clear_fails(key)
        print(f"[login-lock] {key} 密码验证通过，发放 token", flush=True)
        token = create_access_token(user.username)
        return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
