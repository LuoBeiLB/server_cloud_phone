# 后端镜像 —— X86 云手机平台 API（FastAPI + uvicorn）
# 构建上下文：./backend
# 运行：uvicorn app.main:app --host 0.0.0.0 --port 8000
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# 环境：不写 .pyc、日志实时刷出
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 软件源：默认走国内镜像。
#
# 实测：不配源时 `pip install -r requirements.txt` 在国内网络要 **441 秒**；
# 换清华源后是秒级。前端 Dockerfile 早就做了 ARG NPM_REGISTRY，后端一直漏了。
# 境外 CI / 已配企业内网源时可覆盖回官方：
#     docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple \
#                          --build-arg APT_MIRROR=deb.debian.org
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn

# 系统依赖：
#   curl        —— 容器健康检查（/api/health）
#   adb         —— 仅 CLOUD_DEVICE_BACKEND=redroid 时用到（下发 adb 指令）；simulator 用不到但预装无害
# 说明：requirements.txt 里的 docker SDK 带 `platform_system == "Linux"` 标记，
#      本镜像是 Linux，会一并装上，供 redroid 模式通过挂载 docker.sock 操作宿主容器。
RUN if [ -n "${APT_MIRROR}" ] && [ "${APT_MIRROR}" != "deb.debian.org" ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null \
        || sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl adb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt ./
RUN pip install -i "${PIP_INDEX_URL}" \
        --trusted-host "$(echo "${PIP_INDEX_URL}" | sed -E 's#https?://([^/]+).*#\1#')" \
        -r requirements.txt

# 再拷贝应用源码
COPY . .

EXPOSE 8000

# 默认库为 SQLite；compose 中通过 CLOUD_DATABASE_URL 覆盖为 Postgres。
# 生产不加 --reload。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
