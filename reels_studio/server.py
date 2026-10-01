"""Local HTTP server: static GUI + JSON API. Binds to 127.0.0.1 only."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, config, env, jobs, kit, projects
from .jobs import UserFacingError

STATIC = Path(__file__).with_name("static")
TOKEN = secrets.token_urlsafe(24)
MAX_UPLOAD = 8 << 30   # 8 GB per file


def workspace() -> str:
    ws = config.load()["workspace"]
    if not ws:
        raise UserFacingError("請先到「設定」選擇素材資料夾")
    return ws


def ready_workspace() -> str:
    ws = workspace()
    if not kit.installed(ws):
        raise UserFacingError("素材資料夾裡還沒有剪輯引擎，請到「環境檢查」安裝 video-autopilot-kit")
    return ws


class Handler(BaseHTTPRequestHandler):
    server_version = "ReelsStudio/" + __version__
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # ------------------------------------------------------------ plumbing
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            return self._error("forbidden", 403)
        url = urlparse(self.path)
        path, query = unquote(url.path), parse_qs(url.query)
        if method != "GET" and self.headers.get("X-Studio-Token") != TOKEN:
            return self._error("forbidden", 403)
        try:
            for pattern, verb, fn in ROUTES:
                m = re.fullmatch(pattern, path)
                if m and verb == method:
                    return fn(self, query, *m.groups())
            self._error("找不到這個頁面", 404)
        except UserFacingError as exc:
            self._error(str(exc), 400)
        except (ValueError, KeyError) as exc:
            self._error("要求格式不正確：%s" % exc, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    # ------------------------------------------------------------ files
    def _file(self, path: Path, ctype: str | None = None) -> None:
        if not path.is_file():
            return self._error("找不到檔案", 404)
        ctype = ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else end
            else:
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                return self.end_headers()
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _upload_length(self) -> int:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise UserFacingError("檔案是空的")
        if length > MAX_UPLOAD:
            raise UserFacingError("檔案超過 8 GB，請先裁短")
        return length


# ---------------------------------------------------------------- handlers

def h_index(h: Handler, q):
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", TOKEN)
    h._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
            {"Content-Security-Policy": "default-src 'self'; img-src 'self' data:; media-src 'self'; "
             "style-src 'self' 'unsafe-inline'; font-src 'self'; "
             "connect-src 'self'"})


def h_static(h: Handler, q, name):
    target = (STATIC / name).resolve()
    if STATIC.resolve() not in target.parents:
        return h._error("找不到檔案", 404)
    h._file(target)


def h_state(h: Handler, q):
    cfg = config.load()
    h._json({"config": cfg, "version": __version__, "default_workspace": config.default_workspace(),
             "platform": sys.platform, "kit_installed": kit.installed(cfg["workspace"])})


def h_config(h: Handler, q):
    patch = h._body()
    if "workspace" in patch:
        ws = str(patch["workspace"]).strip()
        if not ws or not os.path.isabs(ws):
            raise UserFacingError("請輸入完整的資料夾路徑，例如 G:\\影片製作\\202608P4")
    h._json(config.update(patch))


def h_pick_folder(h: Handler, q):
    code = ("import tkinter as t, tkinter.filedialog as f; r=t.Tk(); r.withdraw(); r.attributes('-topmost', True); "
            "print(f.askdirectory(title='選擇素材資料夾') or '')")
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600,
                             encoding="utf-8").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    h._json({"path": os.path.normpath(out) if out else ""})


def h_env(h: Handler, q):
    h._json({"items": env.status(config.load()["workspace"])})


def h_env_install(h: Handler, q):
    item = h._body()["item"]
    ws = config.load()["workspace"]
    names = {i["id"]: i["name"] for i in env.status(ws)}
    steps = {"kit": ["下載安裝程式", "安裝並驗證檔案"], "wenkai": ["下載 Regular", "下載 Medium"],
             "ffmpeg": ["下載並安裝", "確認可以使用"]}.get(item, ["安裝"])
    job = jobs.start("install:" + item, "安裝 " + names.get(item, item), steps,
                     lambda j: env.install(item, ws, j))
    h._json(job.as_dict())


def h_kit_update(h: Handler, q):
    ws = ready_workspace()
    h._json(env.check_kit_update(ws))


def h_job(h: Handler, q, jid):
    job = jobs.get(jid)
    if not job:
        return h._error("找不到這個工作", 404)
    h._json(job.as_dict())


def h_projects(h: Handler, q):
    cfg = config.load()
    ws = cfg["workspace"]
    h._json({"projects": projects.list_all(ws) if ws and kit.installed(ws) else []})


def h_project_create(h: Handler, q):
    b = h._body()
    h._json(projects.create(ready_workspace(), b.get("title", ""), b.get("what", ""), b.get("addr", "")))


def h_project_get(h: Handler, q, pid):
    ws = ready_workspace()
    p = projects.load(ws, pid)
    p["has_output"] = projects.output_path(ws, pid).is_file()
    h._json(p)


def h_project_edit(h: Handler, q, pid):
    h._json(projects.apply_edits(ready_workspace(), pid, h._body()))


def h_project_delete(h: Handler, q, pid):
    projects.delete(ready_workspace(), pid)
    h._json({"ok": True})


def h_clip_upload(h: Handler, q, pid):
    name = (q.get("name") or [""])[0]
    h._json(projects.add_clip(ready_workspace(), pid, name, h.rfile, h._upload_length()))


def h_scan(h: Handler, q, pid):
    ws = ready_workspace()
    if not env.find_ffmpeg():
        raise UserFacingError("缺少 ffmpeg，請先到「環境檢查」安裝")
    job = jobs.start("scan:" + pid, "分析素材", projects.SCAN_STEPS, lambda j: projects.scan(ws, pid, j))
    h._json(job.as_dict())


def h_check(h: Handler, q, pid):
    h._json(projects.check(ready_workspace(), pid))


def h_build(h: Handler, q, pid):
    ws = ready_workspace()
    missing = [i["name"] for i in env.status(ws) if i["required"] and not i["ok"]]
    if missing:
        raise UserFacingError("缺少 %s，請先到「環境檢查」安裝" % "、".join(missing))
    if jobs.running("build:"):
        raise UserFacingError("另一支影片正在輸出，請等它完成")
    job = jobs.start("build:" + pid, "輸出影片", projects.BUILD_STEPS, lambda j: projects.build(ws, pid, j))
    h._json(job.as_dict())


def h_approve(h: Handler, q, pid):
    h._json(projects.approve(ready_workspace(), pid))


def h_thumb(h: Handler, q, pid, idx):
    h._file(projects.project_dir(ready_workspace(), pid) / "_studio" / ("seg%s.jpg" % int(idx)), "image/jpeg")


def h_video(h: Handler, q, pid):
    h._file(projects.output_path(ready_workspace(), pid), "video/mp4")


def h_qa(h: Handler, q, pid):
    h._json(projects.read_qa(ready_workspace(), pid))


def h_reveal(h: Handler, q, pid):
    ws = ready_workspace()
    out = projects.output_path(ws, pid)
    target = out if out.is_file() else projects.project_dir(ws, pid)
    open_in_file_manager(target)
    h._json({"ok": True, "path": str(target)})


def open_in_file_manager(target: Path) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(target)] if target.is_file() else ["explorer", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target.parent if target.is_file() else target)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def h_bgm(h: Handler, q):
    h._json({"folders": projects.bgm_library(ready_workspace())})


def h_bgm_upload(h: Handler, q):
    folder = (q.get("folder") or [""])[0]
    name = (q.get("name") or [""])[0]
    projects.add_bgm(ready_workspace(), folder, name, h.rfile, h._upload_length())
    h._json({"folders": projects.bgm_library(ready_workspace())})


def h_bgm_file(h: Handler, q):
    root = kit.bgm_root(ready_workspace()).resolve()
    target = (root / (q.get("folder") or [""])[0] / (q.get("name") or [""])[0]).resolve()
    if root not in target.parents:
        return h._error("找不到檔案", 404)
    h._file(target)


ROUTES = [
    (r"/", "GET", h_index),
    (r"/static/([\w.-]+)", "GET", h_static),
    (r"/api/state", "GET", h_state),
    (r"/api/config", "POST", h_config),
    (r"/api/pick-folder", "POST", h_pick_folder),
    (r"/api/env", "GET", h_env),
    (r"/api/env/install", "POST", h_env_install),
    (r"/api/env/kit-update", "POST", h_kit_update),
    (r"/api/jobs/(\w+)", "GET", h_job),
    (r"/api/projects", "GET", h_projects),
    (r"/api/projects", "POST", h_project_create),
    (r"/api/projects/([\w-]+)", "GET", h_project_get),
    (r"/api/projects/([\w-]+)", "POST", h_project_edit),
    (r"/api/projects/([\w-]+)", "DELETE", h_project_delete),
    (r"/api/projects/([\w-]+)/clips", "PUT", h_clip_upload),
    (r"/api/projects/([\w-]+)/scan", "POST", h_scan),
    (r"/api/projects/([\w-]+)/check", "POST", h_check),
    (r"/api/projects/([\w-]+)/build", "POST", h_build),
    (r"/api/projects/([\w-]+)/approve", "POST", h_approve),
    (r"/api/projects/([\w-]+)/thumb/(\d+)", "GET", h_thumb),
    (r"/api/projects/([\w-]+)/video", "GET", h_video),
    (r"/api/projects/([\w-]+)/qa", "GET", h_qa),
    (r"/api/projects/([\w-]+)/reveal", "POST", h_reveal),
    (r"/api/bgm", "GET", h_bgm),
    (r"/api/bgm", "PUT", h_bgm_upload),
    (r"/api/bgm/file", "GET", h_bgm_file),
]


def make_server(port: int) -> ThreadingHTTPServer:
    for candidate in [port] + list(range(port + 1, port + 20)) + [0]:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            srv.daemon_threads = True
            return srv
        except OSError:
            continue
    raise OSError("找不到可用的連接埠")
