"""Per-user settings stored outside the workspace (~/.reels-studio/config.json)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("REELS_STUDIO_HOME") or (Path.home() / ".reels-studio"))
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_PROFILE = {
    "tagline": "",
    "face": "會露臉",
    "platforms": ["IG Reels"],
    "lang": "繁體中文",
    "niche": "travel",
}

_lock = threading.Lock()


def default_workspace() -> str:
    return str(Path.home() / "Videos" / "ReelsStudio")


def load() -> dict:
    data: dict = {}
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    profile = dict(DEFAULT_PROFILE)
    profile.update(data.get("profile") or {})
    return {
        "workspace": data.get("workspace") or "",
        "profile": profile,
        "setup_done": bool(data.get("setup_done")),
    }


def save(cfg: dict) -> dict:
    with _lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    return cfg


def update(patch: dict) -> dict:
    cfg = load()
    if "workspace" in patch:
        cfg["workspace"] = str(patch["workspace"]).strip()
    if "profile" in patch and isinstance(patch["profile"], dict):
        cfg["profile"].update({k: v for k, v in patch["profile"].items() if k in DEFAULT_PROFILE})
    if "setup_done" in patch:
        cfg["setup_done"] = bool(patch["setup_done"])
    return save(cfg)
