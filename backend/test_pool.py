"""预热池本地测试脚本（无需 Docker / Linux 服务器）

用法：在 backend/ 目录下执行
    .venv\Scripts\python test_pool.py

测试内容：
    1. 预热池初始化（创建 3 台 simulator 设备）
    2. acquire() 从池子取设备
    3. batch_create 优先用池子
    4. 补货循环
    5. shutdown 清理
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# 确保当前目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制使用 SQLite + simulator（不依赖 .env 文件）
os.environ["CLOUD_DATABASE_URL"] = "sqlite+aiosqlite:///./test_pool.db"
os.environ["CLOUD_DEVICE_BACKEND"] = "simulator"


async def main():
    from app.database import init_db, SessionLocal, engine
    from app.pool import pool

    # ── 1. 初始化数据库 ──
    print("=" * 60)
    print("1. 初始化数据库...")
    await init_db()
    print("   ✓ 数据库就绪")

    # ── 2. 初始化预热池（3 台，减少等待时间） ──
    print("\n" + "=" * 60)
    print("2. 初始化预热池（3 台）...")
    pool.size = 3  # 缩小池子方便测试
    try:
        await asyncio.wait_for(pool.init(SessionLocal), timeout=30)
    except asyncio.TimeoutError:
        print("   ⚠ 预热池初始化超时（simulator 不应该超时，检查后端）")
        return

    pool_size = pool.pool_size()
    print(f"   池子当前大小: {pool_size}")
    if pool_size >= 3:
        print("   ✓ 预热池初始化成功")
    else:
        print(f"   ⚠ 预期 3 台，实际 {pool_size} 台")

    # ── 3. 测试 acquire() ──
    print("\n" + "=" * 60)
    print("3. 测试 acquire()...")
    device = await pool.acquire()
    if device is not None:
        print(f"   ✓ 取到设备: id={device.id}, name={device.name}, status={device.status}")
        print(f"   池子剩余: {pool.pool_size()}")
    else:
        print("   ✗ 池子为空！")

    # 再取一台
    device2 = await pool.acquire()
    if device2 is not None:
        print(f"   ✓ 取到第二台: id={device2.id}, name={device2.name}")
        print(f"   池子剩余: {pool.pool_size()}")
    else:
        print("   ⚠ 第二台池子为空（可能还在初始化）")

    # ── 4. 测试 batch_create（优先从池子取） ──
    print("\n" + "=" * 60)
    print("4. 测试 batch_create（从池子取 + 后台启动）...")
    from app.routers.devices import batch_create
    from app.schemas import DeviceBatchCreate
    from app.database import get_db

    body = DeviceBatchCreate(
        count=2,
        name_prefix="test",
        width=720,
        height=1280,
        dpi=320,
        auto_start=True,
    )

    async for db in get_db():
        try:
            devices = await batch_create(body, db)
            print(f"   ✓ batch_create 返回 {len(devices)} 台设备")
            for d in devices:
                pool_tag = "池子" if d.status.value == "running" else "新建(后台启动中)"
                print(f"     - id={d.id}, name={d.name}, status={d.status.value} [{pool_tag}]")
        finally:
            break

    # ── 5. 等补货 ──
    print("\n" + "=" * 60)
    print("5. 等待补货（15 秒）...")
    print(f"   补货前池子大小: {pool.pool_size()}")
    await asyncio.sleep(15)
    print(f"   补货后池子大小: {pool.pool_size()}")
    if pool.pool_size() > 0:
        print("   ✓ 补货正常")
    else:
        print("   ⚠ 补货未完成（可能 simulator 的 create_device 有问题）")

    # ── 6. 测试 shutdown ──
    print("\n" + "=" * 60)
    print("6. 测试 shutdown...")
    await pool.shutdown()
    print(f"   池子大小: {pool.pool_size()}")
    print("   ✓ shutdown 完成")

    # ── 7. 清理测试数据库 ──
    print("\n" + "=" * 60)
    print("7. 清理...")
    await engine.dispose()
    db_path = "test_pool.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"   ✓ 已删除 {db_path}")
    print("   ✓ 全部测试完成")


if __name__ == "__main__":
    print("预热池本地测试")
    print("=" * 60)
    print("环境: SQLite + Simulator 后端")
    print("不需要 Docker / Linux 服务器")
    print("=" * 60)
    print()

    asyncio.run(main())