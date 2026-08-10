#!/usr/bin/env python3
"""把壁纸里「画上去的」Dock 底板与页面指示点抹掉，只保留纯渐变。

为什么要做这件事
----------------
早期的 iOS 皮肤壁纸把 Dock 的半透明圆角底板和页面指示点**直接画进了 PNG**。
它是静态美术，位置按 720×1280 固定；而真实的 Dock 图标是 Lawnchair 按设备几何
排布的。实测（redroid，物理 720×1280 被 wm override 成 1080×1920）：

    壁纸里画的底板  按比例映射到 1920 高 → y ≈ 1485..1680
    Lawnchair 实际图标（uiautomator 实测） → y = 1648..1888

图标比底板低约 170px 且顶到屏幕底边，肉眼就是「四个应用偏移跑出了底板」。
分辨率 / 密度 / 导航栏形态任意一项变化都会破坏对齐 —— 假底板注定对不准，
不如不要：真实观感由图标 + 渐变壁纸提供，Dock 底板交给启动器自己画（或不画）。

用法
----
    python3 deploy/ios-skin/strip-dock-plate.py backend/app/skins/wallpaper_*.png

纯标准库（zlib + struct），不依赖 Pillow —— 交付机与 CI 上都不一定装得到。
就地改写，改前自动备份为 *.orig.png（已存在则不覆盖）。
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


# ---------------------------------------------------------------- PNG 编解码
def _read_png(path: Path) -> tuple[int, int, int, list[bytearray]]:
    """返回 (宽, 高, 每像素字节数, 逐行像素)。仅支持 8bit 真彩（PNG 色彩类型 2/6）。"""
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} 不是 PNG")
    pos, idat, w = 8, bytearray(), None
    h = bpp = 0
    while pos < len(raw):
        (ln,) = struct.unpack(">I", raw[pos : pos + 4])
        typ = raw[pos + 4 : pos + 8]
        body = raw[pos + 8 : pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, color = (*struct.unpack(">IIBB", body[:10]),)
            if depth != 8 or color not in (2, 6):
                raise ValueError(f"{path}: 仅支持 8bit RGB/RGBA，实际 depth={depth} color={color}")
            bpp = 3 if color == 2 else 4
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
        pos += 12 + ln

    data = zlib.decompress(bytes(idat))
    stride = w * bpp
    rows: list[bytearray] = []
    prev = bytearray(stride)
    i = 0
    for _ in range(h):
        ft = data[i]
        i += 1
        cur = bytearray(data[i : i + stride])
        i += stride
        # PNG 逐行滤波还原（0 None / 1 Sub / 2 Up / 3 Average / 4 Paeth）
        for x in range(stride):
            a = cur[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ft == 1:
                cur[x] = (cur[x] + a) & 0xFF
            elif ft == 2:
                cur[x] = (cur[x] + b) & 0xFF
            elif ft == 3:
                cur[x] = (cur[x] + ((a + b) >> 1)) & 0xFF
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[x] = (cur[x] + pr) & 0xFF
        rows.append(cur)
        prev = cur
    return w, h, bpp, rows


def _write_png(path: Path, w: int, h: int, bpp: int, rows: list[bytearray]) -> None:
    """以滤波类型 0 重新编码（体积略大但绝对可靠）。"""
    buf = bytearray()
    for r in rows:
        buf.append(0)
        buf += r

    def chunk(typ: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + typ + body + struct.pack(
            ">I", zlib.crc32(typ + body) & 0xFFFFFFFF
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2 if bpp == 3 else 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(buf), 9))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------- 检测与修复
def _detect_overlay_rows(w: int, h: int, bpp: int, rows: list[bytearray]) -> tuple[int, int]:
    """找出被「画上去的东西」污染的行区间。

    判据是**水平方向的硬边**：底板是圆角矩形，左右两侧有明显的亮度阶跃；
    而壁纸本身是平滑渐变（哪怕是斜向渐变），相邻像素差都很小。
    不能用「中心 vs 边缘」的差值 —— 斜向渐变本来就处处有差，会把大半张图误判进去。
    """
    step: list[int] = []
    for y in range(h):
        r = rows[y]
        mx = 0
        for x in range(1, w):
            d = abs(r[x * bpp] - r[(x - 1) * bpp]) + abs(r[x * bpp + 1] - r[(x - 1) * bpp + 1])
            if d > mx:
                mx = d
        step.append(mx)
    base = sorted(step)[len(step) // 2]  # 纯渐变行的典型相邻差
    thr = max(base + 6, 8)
    hits = [y for y in range(int(h * 0.55), h) if step[y] > thr]  # 只在下半部分找
    if not hits:
        return (0, 0)
    # 只取**连续**的一段（底板本体），避免把零散噪点行也圈进来
    hits.sort()
    best_a = best_b = a = hits[0]
    for y in hits[1:]:
        if y - a <= 6:  # 允许小间隙（圆角处阶跃会变弱）
            pass
        else:
            if a - best_a > best_b - best_a:
                best_b = a
            if a - best_a >= best_b - best_a:
                best_b = a
            best_a = y
        a = y
    lo, hi = min(hits), max(hits)
    # 底板高度不应超过画面的 25%；超了说明检测跑偏，宁可不改
    if (hi - lo) > h * 0.25:
        return (0, 0)
    return (max(0, lo - 3), min(h - 1, hi + 3))


def _repair(w: int, h: int, bpp: int, rows: list[bytearray], y0: int, y1: int) -> None:
    """用区间上下两行做逐像素线性插值，还原平滑渐变。"""
    top = rows[y0 - 1] if y0 > 0 else rows[0]
    bot = rows[y1 + 1] if y1 + 1 < h else rows[h - 1]
    span = (y1 - y0) + 2
    for y in range(y0, y1 + 1):
        t = (y - y0 + 1) / span
        r = rows[y]
        for x in range(w * bpp):
            r[x] = int(top[x] * (1 - t) + bot[x] * t)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    for name in argv[1:]:
        p = Path(name)
        if not p.exists():
            print(f"  ✗ {p} 不存在")
            continue
        w, h, bpp, rows = _read_png(p)
        y0, y1 = _detect_overlay_rows(w, h, bpp, rows)
        if y1 <= y0:
            print(f"  - {p.name}: 未检出画上去的底板，跳过")
            continue
        bak = p.with_suffix(".orig.png")
        if not bak.exists():
            bak.write_bytes(p.read_bytes())
        _repair(w, h, bpp, rows, y0, y1)
        _write_png(p, w, h, bpp, rows)
        print(f"  ✓ {p.name}: 抹除 y={y0}..{y1}（占高 {(y1-y0+1)/h:.1%}），备份 {bak.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
