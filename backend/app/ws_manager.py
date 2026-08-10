"""WebSocket 连接管理：向所有前端广播设备状态变化、批量进度、预览帧。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class WSManager:
    def __init__(self) -> None:
        self._conns: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._conns):
            try:
                await ws.send_text(data)
            except Exception:  # noqa: BLE001  连接可能已断
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._conns.discard(ws)

    @property
    def count(self) -> int:
        return len(self._conns)


manager = WSManager()
