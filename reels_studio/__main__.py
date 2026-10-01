"""Start Reels Studio: `python -m reels_studio`."""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from . import __version__, config
from .server import make_server


def main() -> int:
    ap = argparse.ArgumentParser(prog="reels_studio", description="卷家 Reels 工作室")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--workspace", help="素材資料夾（會記住）")
    ap.add_argument("--no-browser", action="store_true", help="不要自動開啟瀏覽器")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    if sys.version_info < (3, 9):
        print("Reels 工作室需要 Python 3.9 以上")
        return 1
    if args.workspace:
        config.update({"workspace": args.workspace})

    srv = make_server(args.port)
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    print("Reels 工作室 %s 已啟動：%s" % (__version__, url))
    print("關閉這個視窗就會結束程式。")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
