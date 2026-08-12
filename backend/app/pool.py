"""设备预热池：后台维护 N 台已启动的空闲容器，分配时秒级返回。

设计原则：
1. 池子是"加速"不是"必须"——空了走异步启动兜底
2. 容器是完整可用的，分配后改名 + 改归属即可
3. 补货慢于消费时自动降级，不阻塞用户
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .database import SessionLocal
from .models import Device, DeviceStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)

# 默认池子大小
DEFAULT_POOL_SIZE = 5
# 补货检查间隔（秒）
REPLENISH_INTERVAL = 10


class DevicePool:
    """设备预热池。

    后台常驻 N 台已启动好的空闲容器，用户批量创建时优先分配。
    池子空了自动走异步创建 + 后台启动兜底，不阻塞用户请求。
    """

    def __init__(self, size: int = DEFAULT_POOL_SIZE):
        self.size = size
        self._ready: asyncio.Queue[Device] = asyncio.Queue(maxsize=size * 2)
        self._replenish_task: asyncio.Task | None = None
        self._initialized = False

    # ── 公开 API ──────────────────────────────────────────

    async def init(self, session_factory: async_sessionmaker | None = None) -> None:
        """启动时预热第一批容器。幂等，重复调用不重复初始化。"""
        if self._initialized:
            return
        if session_factory is None:
            session_factory = SessionLocal

        logger.info("预热池：初始化 %d 台容器...", self.size)
        tasks = [self._create_and_warm(session_factory) for _ in range(self.size)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if not isinstance(r, BaseException))
        logger.info("预热池：初始化完成，%d/%d 成功", success, self.size)

        self._initialized = True
        self._replenish_task = asyncio.create_task(self._replenish_loop(session_factory))

    async def acquire(self) -> Device | None:
        """从池子取一台已启动的设备。池空返回 None（调用方走兜底）。"""
        try:
            device = self._ready.get_nowait()
            logger.info("预热池：分配设备 %d（%s），池内剩余 %d",
                        device.id, device.name, self._ready.qsize())
            return device
        except asyncio.QueueEmpty:
            return None

    def pool_size(self) -> int:
        """当前池子里的设备数。"""
        return self._ready.qsize()

    async def shutdown(self) -> None:
        """停止补货，清理池子里的容器。"""
        if self._replenish_task:
            self._replenish_task.cancel()
            self._replenish_task = None
        while not self._ready.empty():
            try:
                device = self._ready.get_nowait()
                async with SessionLocal() as db:
                    from .services import destroy_device
                    await destroy_device(db, device)
            except Exception:
                logger.exception("预热池：清理设备 %d 失败", device.id if 'device' in dir() else "?")

    # ── 内部实现 ──────────────────────────────────────────

    async def _create_and_warm(self, session_factory: async_sessionmaker) -> Device:
        """创建一台容器并启动到 running 状态，放入池子。"""
        from .services import create_device

        async with session_factory() as db:
            device = await create_device(
                db,
                name=f"_pool_{id(self) % 10000}_{asyncio.get_event_loop().time():.0f}",
                group_id=None,
                width=720,
                height=1280,
                dpi=320,
                auto_start=True,
            )
            if device.status == DeviceStatus.running:
                await self._ready.put(device)
                logger.info("预热池：新设备 %d 已就绪", device.id)
            else:
                logger.warning("预热池：设备 %d 启动失败，状态=%s", device.id, device.status)
            return device

    async def _replenish_loop(self, session_factory: async_sessionmaker) -> None:
        """后台补货循环：保持池子 >= self.size 台。"""
        while True:
            try:
                current = self._ready.qsize()
                needed = self.size - current
                if needed > 0:
                    logger.info("预热池：补货 %d 台（当前 %d/%d）", needed, current, self.size)
                    tasks = [
                        self._create_and_warm(session_factory)
                        for _ in range(needed)
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:
                logger.exception("预热池：补货异常")
            await asyncio.sleep(REPLENISH_INTERVAL)


# 全局单例
pool = DevicePool()