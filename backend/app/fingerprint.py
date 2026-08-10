"""一机一码（D3 / D5）：为每台云手机生成互不相同的设备标识 + 浏览器指纹 + 出口网络。

对齐 demo 验收清单第 4 条「独立身份」：
    抽查 3 台，设备标识 / 出口 IP / 浏览器指纹各不相同。

设计要点：
- 每台设备用一个稳定 seed（来自 uuid）派生全部字段，保证同一设备重启后指纹一致，
  不同设备之间字段互不相同。
- 生成的 `props` 可直接作为 Redroid 启动参数注入（RedroidBackend 使用）。
- `browser` 字段供页面/脚本注入到 Chromium（UA/时区/语言/WebGL/Canvas 噪声）。
"""
from __future__ import annotations

import hashlib
import random
import uuid

# 设备机型库（品牌 / 厂商 / 机型 / 典型分辨率）
_DEVICE_MODELS = [
    ("google", "Google", "Pixel 6", "Pixel 6"),
    ("google", "Google", "Pixel 7 Pro", "Pixel 7 Pro"),
    ("samsung", "Samsung", "SM-G991B", "Galaxy S21"),
    ("samsung", "Samsung", "SM-S918B", "Galaxy S23 Ultra"),
    ("Xiaomi", "Xiaomi", "M2101K9G", "Mi 11"),
    ("Xiaomi", "Xiaomi", "2210132C", "Xiaomi 13"),
    ("OnePlus", "OnePlus", "NE2213", "OnePlus 10 Pro"),
    ("oppo", "OPPO", "PGEM10", "OPPO Find X5"),
    ("vivo", "vivo", "V2254A", "vivo X90"),
    ("HUAWEI", "HUAWEI", "ALN-AL00", "HUAWEI Mate 60"),
]

_TIMEZONES = [
    "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Asia/Tokyo",
    "America/New_York", "America/Los_Angeles", "Europe/London", "Europe/Berlin",
]
_LANGUAGES = ["zh-CN", "zh-TW", "en-US", "en-GB", "ja-JP", "ko-KR"]
_GL_VENDORS = ["Qualcomm", "ARM", "Google Inc.", "Imagination Technologies"]
_GL_RENDERERS = [
    "Adreno (TM) 660", "Adreno (TM) 730", "Mali-G78 MP14", "Mali-G710 MC10",
    "PowerVR Rogue GE8320", "Adreno (TM) 740",
]
_CHROME_VERSIONS = ["118.0.5993.112", "120.0.6099.230", "121.0.6167.101", "122.0.6261.90"]


def _rand_mac(rng: random.Random) -> str:
    return ":".join(f"{rng.randint(0, 255):02x}" for _ in range(6))


def _rand_ip(rng: random.Random) -> str:
    # demo 用：从常见公网段随机一个「出口 IP」展示；真实出口由 proxy_pool 决定。
    return f"{rng.choice([27, 39, 58, 101, 112, 120, 183, 202])}." \
           f"{rng.randint(1, 254)}.{rng.randint(1, 254)}.{rng.randint(1, 254)}"


def generate_fingerprint(seed: str | None = None, proxy: str | None = None) -> dict:
    """生成一份完整指纹。seed 为空时随机，返回值中带回 seed 以便复现。"""
    seed = seed or uuid.uuid4().hex
    rng = random.Random(seed)

    brand, manufacturer, model, marketing = rng.choice(_DEVICE_MODELS)
    android_id = hashlib.sha1(f"aid-{seed}".encode()).hexdigest()[:16]
    serialno = "SN" + hashlib.sha1(f"sn-{seed}".encode()).hexdigest()[:10].upper()
    imei = "".join(str(rng.randint(0, 9)) for _ in range(15))
    mac = _rand_mac(rng)
    chrome = rng.choice(_CHROME_VERSIONS)
    android_ver = rng.choice(["12", "13", "14"])
    width, height = rng.choice([(1080, 2400), (1080, 1920), (1440, 3200), (720, 1600)])
    dpi = rng.choice([320, 400, 440, 480, 560])

    user_agent = (
        f"Mozilla/5.0 (Linux; Android {android_ver}; {model}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome} Mobile Safari/537.36"
    )

    return {
        "seed": seed,
        # --- 设备标识（Redroid props 注入）---
        "device": {
            "brand": brand,
            "manufacturer": manufacturer,
            "model": model,
            "marketing_name": marketing,
            "android_id": android_id,
            "serialno": serialno,
            "imei": imei,
            "mac": mac,
            "android_version": android_ver,
        },
        # --- 浏览器指纹（Chromium 注入）---
        "browser": {
            "user_agent": user_agent,
            "chrome_version": chrome,
            "width": width,
            "height": height,
            "dpi": dpi,
            "device_pixel_ratio": round(dpi / 160, 2),
            "timezone": rng.choice(_TIMEZONES),
            "language": rng.choice(_LANGUAGES),
            "webgl_vendor": rng.choice(_GL_VENDORS),
            "webgl_renderer": rng.choice(_GL_RENDERERS),
            # canvas / audio 指纹噪声种子：注入脚本据此对每台设备加固定微扰
            "canvas_noise_seed": hashlib.sha1(f"canvas-{seed}".encode()).hexdigest()[:12],
            "hardware_concurrency": rng.choice([4, 6, 8]),
            "device_memory": rng.choice([4, 6, 8, 12]),
        },
        # --- 网络（独立出口 IP / 代理位）---
        "network": {
            "proxy": proxy,
            "exit_ip": _rand_ip(rng),
        },
    }


def redroid_props(fp: dict) -> list[str]:
    """把指纹转成 Redroid 设备标识 props（ro.*）。

    注意：只注入设备标识；显示参数(width/height/dpi)由设备记录在 create() 时单独指定，
    避免与这里的浏览器指纹分辨率冲突。
    """
    d = fp["device"]
    return [
        f"ro.product.brand={d['brand']}",
        f"ro.product.manufacturer={d['manufacturer']}",
        f"ro.product.model={d['model']}",
        f"ro.product.name={d['model']}",
        f"ro.serialno={d['serialno']}",
        f"androidboot.serialno={d['serialno']}",
    ]
