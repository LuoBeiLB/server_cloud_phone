#!/bin/bash
# 在 Redroid 容器/宿主机上安装 ADBKeyboard 输入法
# 用法: bash install-adbkeyboard.sh [设备序列号]
# 未指定序列号则操作默认设备

set -euo pipefail

ADB="adb"
if [ -n "${1:-}" ]; then
    ADB="adb -s $1"
fi

APK="${APK_PATH:-./ADBKeyboard.apk}"
if [ ! -f "$APK" ]; then
    echo "错误：找不到 ADBKeyboard.apk（$APK）"
    echo "请设置 APK_PATH 环境变量指向 APK 文件"
    exit 1
fi

echo ">> 安装 ADBKeyboard..."
$ADB install -r "$APK"

echo ">> 启用 ADBKeyboard 输入法..."
$ADB shell ime enable com.android.adbkeyboard/.AdbIME

echo ">> 切换到 ADBKeyboard 输入法..."
$ADB shell ime set com.android.adbkeyboard/.AdbIME

echo ">> 完成！ADBKeyboard 已安装并启用"