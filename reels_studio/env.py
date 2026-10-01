"""Detect required software and install it only after the person agrees."""
from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import kit
from .jobs import Job, UserFacingError

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
KIT_INSTALLER = ("https://github.com/Hao0321/video-autopilot-kit/releases/latest/download/"
                 "install_or_upgrade.py")
WENKAI_URL = "https://github.com/lxgw/LxgwWenkaiTC/releases/download/v1.522/LXGWWenKaiTC-%s.ttf"
WENKAI_WEIGHTS = ("Regular", "Medium")
# Same pins as the kit's requirements-media.txt; used before the kit is installed.
MEDIA_PINS = ["Pillow==11.3.0", "qrcode==7.4.2", "numpy==2.0.2", "opencv-contrib-python-headless==4.12.0.88"]
NOFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- detection

def _ffmpeg_extra_dirs() -> list[str]:
    if not IS_WIN:
        return ["/opt/homebrew/bin", "/usr/local/bin"]
    local = os.environ.get("LOCALAPPDATA", "")
    dirs = [os.path.join(local, "Microsoft", "WinGet", "Links")]
    dirs += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "*", "bin"))
    return dirs


def find_ffmpeg() -> str | None:
    """Locate ffmpeg, also in places a fresh winget/brew install uses before PATH refreshes."""
    found = shutil.which("ffmpeg")
    if found and shutil.which("ffprobe"):
        return found
    for d in _ffmpeg_extra_dirs():
        exe = os.path.join(d, "ffmpeg.exe" if IS_WIN else "ffmpeg")
        probe = os.path.join(d, "ffprobe.exe" if IS_WIN else "ffprobe")
        if os.path.isfile(exe) and os.path.isfile(probe):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")  # child processes inherit it
            return exe
    return None


def _ffmpeg_version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10,
                             creationflags=NOFLAGS).stdout
        return out.split()[2] if out.startswith("ffmpeg version") else "已安裝"
    except (OSError, IndexError, subprocess.SubprocessError):
        return "已安裝"


def media_ok() -> tuple[bool, str]:
    code = ("import PIL, numpy, cv2, qrcode; "
            "assert hasattr(cv2, 'TrackerCSRT_create') or hasattr(getattr(cv2, 'legacy', None), 'TrackerCSRT_create'); "
            "print(cv2.__version__)")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                          creationflags=NOFLAGS)
    if proc.returncode == 0:
        return True, "OpenCV " + proc.stdout.strip()
    lines = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
    return False, lines[-1] if lines else ""


def _font_dirs() -> list[Path]:
    if IS_WIN:
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
        return dirs
    if IS_MAC:
        return [Path.home() / "Library" / "Fonts", Path("/Library/Fonts")]
    return [Path.home() / ".local" / "share" / "fonts", Path.home() / ".fonts", Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts")]


def font_installed(family: str, file_glob: str) -> bool:
    if not IS_WIN and shutil.which("fc-list"):
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
        return family.lower() in out.lower()
    for d in _font_dirs():
        if d.is_dir() and any(d.rglob(file_glob)):
            return True
    return False


def status(ws: str) -> list[dict]:
    ffmpeg = find_ffmpeg()
    media, media_ver = media_ok()
    has_kit = kit.installed(ws)
    items = [
        {"id": "python", "name": "Python", "why": "執行剪輯引擎", "required": True, "ok": sys.version_info >= (3, 9),
         "version": platform.python_version()},
        {"id": "ffmpeg", "name": "ffmpeg", "why": "轉檔、剪接、燒字幕、混音", "required": True, "ok": bool(ffmpeg),
         "version": _ffmpeg_version(ffmpeg) if ffmpeg else "", **install_info("ffmpeg")},
        {"id": "media", "name": "影像分析套件", "why": "Pillow、numpy、OpenCV：挑開場畫面與畫質檢查",
         "required": True, "ok": media, "version": media_ver if media else "",
         "detail": "" if media else media_ver, **install_info("media")},
        {"id": "kit", "name": "video-autopilot-kit", "why": "剪輯規則與品質檢查", "required": True, "ok": has_kit,
         "version": kit.version(ws) if has_kit else "", "updatable": has_kit, **install_info("kit", ws)},
        {"id": "wenkai", "name": "霞鶩文楷 TC 字型", "why": "Reels 旅遊字幕字體", "required": True,
         "ok": font_installed("LXGW WenKai TC", "LXGWWenKaiTC*"), "version": "", **install_info("wenkai")},
        {"id": "serif", "name": "Noto Serif TC 字型", "why": "長片字幕字體", "required": False,
         "ok": font_installed("Noto Serif TC", "NotoSerifTC*"), "version": "", "manual_url":
         "https://fonts.google.com/noto/specimen/Noto+Serif+TC",
         "manual": "從 Google Fonts 下載後，對字型檔按右鍵選「安裝」"},
        {"id": "editkin", "name": "Editkin", "why": "可編輯時間軸、長片剪輯", "required": False, "ok": False,
         "version": "", "manual_url": "https://github.com/Hao0321/Editkin",
         "manual": "目前沒有官方安裝檔，要自行從原始碼建置；推出後這裡會出現「安裝」按鈕"},
    ]
    if not ws:
        items[3]["blocked"] = "請先在設定選擇素材資料夾"
    return items


def install_info(item: str, ws: str = "") -> dict:
    """What an install will do, shown to the person before they agree."""
    if item == "ffmpeg":
        if IS_WIN:
            return {"install": "winget install --id Gyan.FFmpeg -e", "size": "約 90 MB"}
        if IS_MAC and shutil.which("brew"):
            return {"install": "brew install ffmpeg", "size": "約 90 MB"}
        return {"manual": "請在終端機執行：sudo apt install ffmpeg（或你的系統對應的套件管理指令）"}
    if item == "media":
        return {"install": "%s -m pip install --user %s" % (Path(sys.executable).name, " ".join(MEDIA_PINS)),
                "size": "約 120 MB"}
    if item == "kit":
        return {"install": "下載 install_or_upgrade.py，安裝到 %s" % (ws or "素材資料夾"), "size": "約 10 MB"}
    if item == "wenkai":
        return {"install": "下載 LXGWWenKaiTC-Regular／Medium.ttf，安裝給目前使用者（不需系統管理員）",
                "size": "約 30 MB"}
    return {}


# ---------------------------------------------------------------- installers

def install(item: str, ws: str, job: Job) -> dict:
    fn = {"ffmpeg": _install_ffmpeg, "media": _install_media, "kit": _install_kit, "wenkai": _install_wenkai}.get(item)
    if not fn:
        raise UserFacingError("這個項目沒有自動安裝，請照畫面說明手動安裝")
    return fn(ws, job) or {}


def _run(args: list[str], job: Job, cwd: str | None = None) -> None:
    job.line("$ " + " ".join(args))
    proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=NOFLAGS)
    assert proc.stdout is not None
    for line in proc.stdout:
        job.line(line)
    if proc.wait() != 0:
        raise UserFacingError("安裝沒有成功（%s 結束代碼 %s）。詳細訊息在下方紀錄。" % (Path(args[0]).name, proc.returncode))


def _install_ffmpeg(ws: str, job: Job) -> None:
    if IS_WIN:
        if not shutil.which("winget"):
            raise UserFacingError("這台電腦沒有 winget。請從 Microsoft Store 安裝「應用程式安裝程式」後再試。")
        _run(["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--accept-source-agreements",
              "--accept-package-agreements"], job)
    elif IS_MAC and shutil.which("brew"):
        _run(["brew", "install", "ffmpeg"], job)
    else:
        raise UserFacingError(install_info("ffmpeg")["manual"])
    job.advance_to(1)
    if not find_ffmpeg():
        raise UserFacingError("ffmpeg 已安裝，但還找不到。請關掉 Reels 工作室再重新開啟。")


def _install_media(ws: str, job: Job) -> None:
    req = kit.ws_path(ws, "requirements-media.txt") if ws else None
    args = [sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check"]
    if os.environ.get("VIRTUAL_ENV"):
        args.remove("--user")
    args += ["-r", str(req)] if req and req.is_file() else MEDIA_PINS
    _run(args, job)


def _download(url: str, dest: Path, job: Job) -> None:
    job.line("下載 " + url)
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as fh:  # nosec B310 - fixed https URLs
        shutil.copyfileobj(resp, fh)


def _install_kit(ws: str, job: Job) -> None:
    if not ws:
        raise UserFacingError("請先在設定選擇素材資料夾")
    Path(ws).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        installer = Path(tmp) / "install_or_upgrade.py"
        _download(KIT_INSTALLER, installer, job)
        job.advance_to(1)
        _run([sys.executable, str(installer), "--install-root", ws, "--apply"], job)
    if not kit.installed(ws):
        raise UserFacingError("安裝程式執行完畢，但資料夾裡找不到剪輯引擎")


def check_kit_update(ws: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        installer = Path(tmp) / "install_or_upgrade.py"
        with urllib.request.urlopen(KIT_INSTALLER, timeout=30) as resp:  # nosec B310
            installer.write_bytes(resp.read())
        proc = subprocess.run([sys.executable, str(installer), "--install-root", ws, "--check"],
                              capture_output=True, text=True, encoding="utf-8", timeout=120, creationflags=NOFLAGS)
    import json
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"status": "FAILED"}


def _install_wenkai(ws: str, job: Job) -> None:
    if IS_WIN:
        target = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
    elif IS_MAC:
        target = Path.home() / "Library" / "Fonts"
    else:
        target = Path.home() / ".local" / "share" / "fonts"
    target.mkdir(parents=True, exist_ok=True)
    for i, weight in enumerate(WENKAI_WEIGHTS):
        dest = target / ("LXGWWenKaiTC-%s.ttf" % weight)
        if not dest.is_file():
            _download(WENKAI_URL % weight, dest, job)
        if IS_WIN:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                  r"Software\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                winreg.SetValueEx(key, "LXGW WenKai TC %s (TrueType)" % weight, 0, winreg.REG_SZ, str(dest))
        job.advance_to(i + 1)
    if not IS_WIN and shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f"], capture_output=True)
