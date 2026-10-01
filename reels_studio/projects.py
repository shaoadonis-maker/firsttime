"""Reels projects: one kit inbox folder each, plus a `_studio.json` the GUI owns."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import kit
from .jobs import Job, UserFacingError

META = "_studio.json"
VIDEO_EXT = {".mp4", ".mov"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}
_lock = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def project_dir(ws: str, pid: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", pid or ""):
        raise UserFacingError("專案編號不正確")
    return kit.inbox(ws) / pid


def load(ws: str, pid: str) -> dict:
    path = project_dir(ws, pid) / META
    if not path.is_file():
        raise UserFacingError("找不到這個專案")
    return json.loads(path.read_text(encoding="utf-8"))


def save(ws: str, p: dict) -> dict:
    p["updated"] = _now()
    d = project_dir(ws, p["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (META + ".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, d / META)
    return p


def list_all(ws: str) -> list[dict]:
    root = kit.inbox(ws)
    out = []
    if root.is_dir():
        for d in root.iterdir():
            if (d / META).is_file():
                try:
                    out.append(summary(json.loads((d / META).read_text(encoding="utf-8"))))
                except (OSError, ValueError):
                    continue
    return sorted(out, key=lambda p: p.get("created", ""), reverse=True)


def summary(p: dict) -> dict:
    return {k: p.get(k) for k in ("id", "title", "status", "created", "updated", "score", "error")} | {
        "thumb": bool(p.get("segs")), "clips": len(p.get("clips", []))}


def create(ws: str, title: str, what: str, addr: str) -> dict:
    title = (title or "").strip()
    if not title:
        raise UserFacingError("請填寫地點名稱")
    # The kit's publish hub only accepts numeric Shorts folder ids (1, 2, 3 …).
    with _lock:
        root = kit.inbox(ws)
        used = [int(d.name) for d in root.iterdir() if d.name.isdigit()] if root.is_dir() else []
        pid = str(max(used, default=0) + 1)
        project_dir(ws, pid).mkdir(parents=True)
    p = {"id": pid, "title": title, "what": (what or "").strip(), "addr": (addr or "").strip(),
         "status": "new", "created": _now(), "clips": [], "segs": [], "caps": [],
         "bgm_folder": "", "bgm_prefer": "energetic", "copy": "", "score": None, "error": ""}
    return save(ws, p)


def delete(ws: str, pid: str) -> None:
    d = project_dir(ws, pid)
    if d.is_dir():
        shutil.rmtree(d)


def add_clip(ws: str, pid: str, original: str, stream, length: int) -> dict:
    ext = Path(original).suffix.lower()
    if ext not in VIDEO_EXT:
        raise UserFacingError("「%s」不是 mp4 或 mov 影片" % original)
    with _lock:
        p = load(ws, pid)
        name = "clip%02d%s" % (len(p["clips"]) + 1, ext)
        p["clips"].append({"file": name, "original": Path(original).name, "size": length})
        save(ws, p)
    dest = project_dir(ws, pid) / name
    _copy_stream(stream, length, dest)
    return p


def _copy_stream(stream, length: int, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    remaining = length
    with open(tmp, "wb") as fh:
        while remaining > 0:
            chunk = stream.read(min(1 << 20, remaining))
            if not chunk:
                break
            fh.write(chunk)
            remaining -= len(chunk)
    if remaining:
        tmp.unlink(missing_ok=True)
        raise UserFacingError("上傳中斷，請再試一次")
    os.replace(tmp, dest)


# ---------------------------------------------------------------- scan

SCAN_STEPS = ["轉成 9:16 直式", "產生縮圖", "挑選開場畫面並排片段", "準備字幕表"]


def scan(ws: str, pid: str, job: Job) -> dict:
    p = load(ws, pid)
    if not p["clips"]:
        raise UserFacingError("還沒有加入任何影片")
    d = project_dir(ws, pid)
    (d / "_plan.py").unlink(missing_ok=True)       # let the kit write a fresh skeleton
    p["status"], p["error"] = "scanning", ""
    save(ws, p)
    try:
        kit.run_streaming([sys.executable, "src/shorts_autopilot.py", "scan", pid], ws, kit.kit_env(ws), job,
                          [("clips normalized", 1), ("contact sheet", 2), ("[auto]", 2), ("plan skeleton", 3)])
        spec, _copy = kit.read_plan(d / "_plan.py")
        by_name = {Path(c["file"]).stem: c["original"] for c in p["clips"]}
        p["segs"] = []
        for i, (path, start, dur) in enumerate(spec.get("segs", [])):
            stem = Path(path).stem
            p["segs"].append({"path": str(path), "in": float(start), "dur": float(dur),
                              "label": by_name.get(stem, stem), "orig_dur": float(dur)})
        if len(p["segs"]) < 2:
            raise UserFacingError("素材太少，至少需要 2 段可用的畫面")
        # White by default: the kit rejects more than 35% of caption characters in a highlight colour.
        p["caps"] = [{"seg": 0, "text": p["title"], "color": "white", "kind": "hook"}]
        if p["what"]:
            p["caps"].append({"seg": 1, "text": p["what"][:8], "color": "white", "kind": "sub"})
        make_thumbs(ws, p)
        p["status"] = "draft"
        job.advance_to(4)
    except UserFacingError as exc:
        p["status"], p["error"] = "error", str(exc)
        save(ws, p)
        raise
    return save(ws, p)


def make_thumbs(ws: str, p: dict) -> None:
    out = project_dir(ws, p["id"]) / "_studio"
    out.mkdir(exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    for i, s in enumerate(p["segs"]):
        t = s["in"] + s["dur"] / 2
        subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", "%.2f" % t, "-i", s["path"], "-frames:v", "1",
                        "-vf", "scale=240:-2", str(out / ("seg%d.jpg" % i))],
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


# ---------------------------------------------------------------- edit / plan

EDITABLE = ("title", "what", "addr", "caps", "bgm_folder", "bgm_prefer", "copy")


def apply_edits(ws: str, pid: str, patch: dict) -> dict:
    p = load(ws, pid)
    for key in EDITABLE:
        if key in patch:
            p[key] = patch[key]
    if "durs" in patch:
        for s, dur in zip(p["segs"], patch["durs"]):
            s["dur"] = round(max(0.5, min(float(dur), 15.0)), 2)
    p["caps"] = sorted(
        [{"seg": int(c["seg"]), "text": str(c.get("text", "")), "color": "gold" if c.get("color") == "gold" else "white",
          "kind": str(c.get("kind") or "sub")} for c in p.get("caps", []) if 0 <= int(c["seg"]) < len(p["segs"])],
        key=lambda c: c["seg"])
    if p["status"] in ("review", "done"):
        p["status"] = "draft"      # an edit after export needs a fresh export
    save(ws, p)
    if p["segs"]:
        write_plan(ws, p)
    return p


def spec_for(p: dict, niche: str) -> dict:
    caps: list = []
    for c in p["caps"]:
        if c["text"].strip():
            kind = "hook" if not caps and c["seg"] == 0 else "sub"
            caps.append((c["seg"], [(c["text"].strip(), c["color"])], kind))
    addr = p["addr"].strip() or "📍 " + p["title"]
    return {
        "name": "s" + p["id"],
        "platform": "ig_reels",
        "niche": niche or "auto",
        "place": p["title"],
        "what": p["what"] or p["title"],
        "addr": addr if addr.startswith("📍") else "📍 " + addr,
        "persistent_label_policy": "intro",
        "location_chip": p["title"],
        "segs": [(s["path"], s["in"], s["dur"]) for s in p["segs"]],
        "caps_by_seg": caps,
        "evidence": {},
        "bgm_folder": p["bgm_folder"],
        "bgm_policy": "folder",
        "bgm_prefer": p.get("bgm_prefer") or "energetic",
    }


def default_copy(p: dict) -> str:
    lines = [c["text"] for c in p["caps"] if c["text"].strip()]
    body = "，".join(lines[:4]) + "。" if lines else p["title"]
    addr = p["addr"].strip() or p["title"]
    tags = " ".join("#" + t for t in dict.fromkeys([p["title"].replace(" ", ""), "家庭旅遊", "日本旅遊", "Reels"]))
    return "%s\n\n📍 %s\n%s" % (body, addr.lstrip("📍 "), tags)


def write_plan(ws: str, p: dict, niche: str = "") -> None:
    from . import config
    niche = niche or config.load()["profile"].get("niche") or "auto"
    copy = {"yt_title": "%s｜%s" % (p["title"], p["what"] or p["title"]), "text": p["copy"] or default_copy(p)}
    kit.write_plan(project_dir(ws, p["id"]) / "_plan.py", spec_for(p, niche), copy)


def check(ws: str, pid: str) -> dict:
    from . import config
    p = load(ws, pid)
    rep = kit.gate_check(ws, spec_for(p, config.load()["profile"].get("niche")))
    if not p["bgm_folder"]:
        rep["fails"].append("還沒選背景音樂")
        rep["ok"] = False
    return rep


# ---------------------------------------------------------------- build

BUILD_STEPS = ["輸出前檢查", "剪接片段並燒入字幕", "混音", "畫面、聲音與循環檢查", "完成"]


def build(ws: str, pid: str, job: Job) -> dict:
    p = load(ws, pid)
    if not p["bgm_folder"]:
        raise UserFacingError("請先選背景音樂")
    write_plan(ws, p)
    p["status"], p["error"] = "building", ""
    save(ws, p)
    try:
        kit.run_streaming([sys.executable, "src/shorts_autopilot.py", "build", pid], ws, kit.kit_env(ws), job,
                          [("[music]", 1), ("[asset-hub]", 1), ("[build]", 1), ("[qa]", 3), ("QUALITY", 3)])
    except UserFacingError as exc:
        p = load(ws, pid)
        p["status"], p["error"] = "draft", str(exc)
        save(ws, p)
        raise
    p = load(ws, pid)
    qa = read_qa(ws, pid)
    p["score"] = qa.get("score")
    p["status"] = "review"
    if not p["copy"]:
        p["copy"] = default_copy(p)
    return save(ws, p)


def output_path(ws: str, pid: str) -> Path:
    return project_dir(ws, pid) / "_out" / "current.mp4"


QA_LABELS = {
    "technical_delivery": "畫面與聲音規格", "truth_and_evidence": "字幕內容有根據",
    "first_frame_and_hook": "開場畫面", "typography_and_safe_area": "字幕位置與字體",
    "transition_motivation": "轉場", "rhythm_and_flow": "節奏", "asset_novelty": "素材不重複",
    "narrative_differentiation": "跟其他支不雷同", "tracking_and_compositing": "追蹤特效",
    "human_aesthetic_review": "你的審片",
}


def read_qa(ws: str, pid: str) -> dict:
    path = project_dir(ws, pid) / "_out" / "_qa" / "QUALITY_95.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    dims = []
    for d in raw.get("dimensions") or []:
        if not isinstance(d, dict):
            continue
        dims.append({"key": d.get("id"), "label": QA_LABELS.get(d.get("id"), d.get("id")),
                     "points": d.get("points"), "max": d.get("weight")})
    return {"score": raw.get("score"), "target": raw.get("target"), "status": raw.get("status"), "dims": dims}


def approve(ws: str, pid: str) -> dict:
    p = load(ws, pid)
    if not output_path(ws, pid).is_file():
        raise UserFacingError("還沒有輸出成品")
    p["status"], p["approved"] = "done", _now()
    return save(ws, p)


# ---------------------------------------------------------------- music library

def bgm_library(ws: str) -> list[dict]:
    root = kit.bgm_root(ws)
    out = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith((".", "_")):
                tracks = [f.name for f in sorted(d.iterdir()) if f.suffix.lower() in AUDIO_EXT]
                out.append({"folder": d.name, "tracks": tracks})
    return out


def add_bgm(ws: str, folder: str, original: str, stream, length: int) -> None:
    folder = folder.strip()
    if not folder or re.search(r'[\\/:*?"<>|]', folder) or folder.startswith("."):
        raise UserFacingError("分類名稱不能有特殊符號")
    name = Path(original).name
    if Path(name).suffix.lower() not in AUDIO_EXT:
        raise UserFacingError("「%s」不是支援的音樂格式（mp3、m4a、wav）" % original)
    dest_dir = kit.bgm_root(ws) / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    _copy_stream(stream, length, dest_dir / name)
