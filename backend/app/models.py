"""数据模型：用户 / 分组 / 设备 / 脚本 / 脚本运行记录。"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceStatus(str, enum.Enum):
    creating = "creating"
    running = "running"
    stopped = "stopped"
    error = "error"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    devices: Mapped[list["Device"]] = relationship(back_populates="group")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus), default=DeviceStatus.stopped, index=True
    )

    # 编排后端引用（容器 id / 模拟器 id）与 adb 端口
    backend_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    adb_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 显示参数
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    dpi: Mapped[int] = mapped_column(Integer, default=480)

    # 皮肤主题（一键换肤）：空=未换肤 | ios | sunset | glass
    #
    # 默认**不是** ios：新建的机器还是原生安卓桌面，换肤是一次真实操作
    #（装 Lawnchair + 写壁纸 + 重启）。默认写 ios 会让列表显示「iOS 风」，
    # 而设备实际是原生样子 —— 又一处「界面说的和真机不符」。
    skin: Mapped[str] = mapped_column(String(32), default="")

    # 最近一次拉起/启动失败的原因（成功时清空）。
    #
    # 存在的意义：过去 services.create_device 用 `except Exception: 标记 error` 把原因
    # 整个吞掉，界面上只有「状态：异常」三个字，甲方无从下手。现在这里存
    # DeviceProvisionError 的「原因 + 处置建议 + 实测证据」，前端直接展示。
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # 当前浏览器页面（demo 主流程：每台开网页）
    current_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 一机一码：设备标识 + 浏览器指纹 + 网络，整体存 JSON
    fingerprint: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    group: Mapped[Group | None] = relationship(back_populates="devices")


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # 步骤列表：[{action, ...params}]，对齐 Airtest .air 用例的抽象
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ScriptRun(Base):
    __tablename__ = "script_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="running")  # running/success/failed
    # 逐设备结果：[{device_id, name, status, steps:[{action, ok, ts}]}]
    results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
