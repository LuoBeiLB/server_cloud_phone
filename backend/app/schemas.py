"""Pydantic 请求/响应模型（API 契约）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .models import DeviceStatus


# --------- 鉴权 ---------
class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --------- 分组 ---------
class GroupCreate(BaseModel):
    name: str
    parent_id: int | None = None


class GroupOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    device_count: int = 0

    class Config:
        from_attributes = True


# --------- 设备 ---------
class DeviceCreate(BaseModel):
    name: str | None = None
    group_id: int | None = None
    width: int = 1080
    height: int = 1920
    dpi: int = 480
    target_url: str | None = None
    proxy: str | None = None


class DeviceBatchDelete(BaseModel):
    """批量删除设备。device_ids 为空则不做任何事（避免误删全部）。"""

    device_ids: list[int] = Field(default_factory=list)


class DeviceBatchCreate(BaseModel):
    count: int = Field(ge=1, le=100)
    name_prefix: str = "云手机"
    group_id: int | None = None
    width: int = 720
    height: int = 1280
    dpi: int = 320
    target_url: str | None = None
    auto_start: bool = True


class DeviceUpdate(BaseModel):
    name: str | None = None
    group_id: int | None = None


class DeviceOut(BaseModel):
    id: int
    name: str
    group_id: int | None
    status: DeviceStatus
    adb_port: int | None
    width: int
    height: int
    dpi: int
    skin: str = ""  # 空 = 未换肤
    current_url: str | None
    fingerprint: dict
    # 最近一次拉起/启动失败的原因（含处置建议）；正常时为 null
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --------- 单机操控 ---------
class TapCmd(BaseModel):
    x: int
    y: int


class SwipeCmd(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = 300


class TextCmd(BaseModel):
    text: str


class KeyCmd(BaseModel):
    key: str  # back / home / menu / power / volume_up / volume_down / enter


class OpenUrlCmd(BaseModel):
    url: str


class InstallCmd(BaseModel):
    apk_url: str


class DisplayCmd(BaseModel):
    width: int = Field(ge=320, le=2160)
    height: int = Field(ge=480, le=3840)
    dpi: int = Field(ge=120, le=640)


# --------- 批量操作 ---------
class BatchTargets(BaseModel):
    device_ids: list[int]


class BatchOpenUrl(BatchTargets):
    url: str


class BatchTap(BatchTargets):
    x: int
    y: int


class BatchSwipe(BatchTargets):
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = 300


class BatchText(BatchTargets):
    text: str


class BatchKey(BatchTargets):
    key: str


class BatchInstall(BatchTargets):
    apk_url: str


class BatchResult(BaseModel):
    total: int
    ok: int
    failed: int
    details: list[dict]


# --------- 脚本录制/回放 ---------
class ScriptStep(BaseModel):
    action: str  # open_url / tap / swipe / text / key / wait
    params: dict = {}


class ScriptCreate(BaseModel):
    name: str
    description: str = ""
    steps: list[ScriptStep] = []


class ScriptOut(BaseModel):
    id: int
    name: str
    description: str
    steps: list
    created_at: datetime

    class Config:
        from_attributes = True


class ScriptRunRequest(BaseModel):
    device_ids: list[int]


class ScriptRunOut(BaseModel):
    id: int
    script_id: int
    status: str
    results: list
    created_at: datetime

    class Config:
        from_attributes = True
