#!/usr/bin/env bash
# 导游鲸宝 · 把「你好鲸宝」唤醒词固件烧进小智 Otto 机器人（macOS / Linux）。
#
# 用法：
#   ./flash.sh                     自动找串口；先整片备份，再烧
#   ./flash.sh /dev/cu.usbmodemXXXX
#   NO_BACKUP=1 ./flash.sh ...     跳过备份（同一台机器人已经备份过时）
#
# 只写 5 块：引导、分区表、OTA 标记、唤醒模型、主程序。
# 不碰 0x9000 那块（NVS：Wi-Fi 密码和小智后台绑定），所以烧完不用重新配网、不用重新绑定。
# 千万别烧编译目录里的 merged-binary.bin：它从 0 地址一路写下去，会把 Wi-Fi 和绑定抹掉。
set -euo pipefail
cd "$(dirname "$0")"

ESPTOOL=(python3 -m esptool)
if ! python3 -m esptool version >/dev/null 2>&1; then
  echo "没装 esptool。先运行：python3 -m pip install 'esptool<5'" >&2
  exit 1
fi

PORT="${1:-}"
if [ -z "$PORT" ]; then
  PORT=$(ls /dev/cu.usbmodem* /dev/ttyACM* 2>/dev/null | head -1 || true)
fi
if [ -z "$PORT" ]; then
  echo "找不到机器人串口。确认：机器人开机、用能传数据的 Type-C 线连电脑。" >&2
  exit 1
fi
echo "串口：$PORT"

echo "== 校验固件文件 =="
(cd bin && shasum -a 256 -c SHA256SUMS.txt)

if [ "${NO_BACKUP:-0}" != "1" ]; then
  mkdir -p backup
  OUT="backup/otto_full16MB_$(date +%Y%m%d_%H%M%S).bin"
  echo "== 先整片备份（约 1 分钟）→ $OUT =="
  echo "   备份里有 Wi-Fi 密码和后台绑定信息：只留在本机，别发群、别提交仓库（backup/ 已在 .gitignore）。"
  "${ESPTOOL[@]}" --chip esp32s3 -p "$PORT" -b 921600 read_flash 0 0x1000000 "$OUT"
fi

echo "== 烧录（约 1 分钟，期间别拔线）=="
"${ESPTOOL[@]}" --chip esp32s3 -p "$PORT" -b 921600 write_flash \
  --flash_mode dio --flash_freq 80m --flash_size 16MB \
  0x0      bin/bootloader.bin \
  0x8000   bin/partition-table.bin \
  0xd000   bin/ota_data_initial.bin \
  0x10000  bin/srmodels.bin \
  0x400000 bin/xiaozhi.bin

echo
echo "烧好了，机器人会自己重启。等屏幕出表情后说「你好鲸宝」试试。"
echo "要恢复成烧之前的样子：python3 -m esptool --chip esp32s3 -p $PORT -b 921600 write_flash 0 <备份文件>"
