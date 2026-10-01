#!/usr/bin/env sh
# Start Reels Studio on macOS / Linux.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "需要 Python 3.9 以上：macOS 可用 brew install python，Linux 用套件管理員安裝 python3。"
  exit 1
fi
exec python3 -m reels_studio "$@"
