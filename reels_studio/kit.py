"""Adapter around an installed video-autopilot-kit workspace.

The kit is never modified: Reels Studio writes the same `_plan.py` a person
would write by hand and runs the kit's own `shorts_autopilot.py scan/build`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .jobs import Job, UserFacingError

SHORTS_INBOX = ("videos", "_INBOX", "直式-vertical-Shorts-Reels")
BGM_ROOT = ("assets", "bgm")
HELPER = Path(__file__).with_name("_gate_helper.py")
CAPTION_FONT = {"travel": "LXGW WenKai TC", "nature": "LXGW WenKai TC", "cafe": "LXGW WenKai TC",
                "food": "Huninn", "dessert": "Huninn", "toy": "Huninn"}


def ws_path(ws: str, *parts: str) -> Path:
    return Path(ws).joinpath(*parts)


def inbox(ws: str) -> Path:
    return ws_path(ws, *SHORTS_INBOX)


def bgm_root(ws: str) -> Path:
    return ws_path(ws, *BGM_ROOT)


def installed(ws: str) -> bool:
    return bool(ws) and ws_path(ws, "AUTOPILOT_MANIFEST.json").is_file() \
        and ws_path(ws, "src", "shorts_autopilot.py").is_file()


def version(ws: str) -> str:
    try:
        state = json.loads(ws_path(ws, ".video-autopilot", "install-state.json").read_text(encoding="utf-8"))
        return str(state.get("version") or "")
    except (OSError, ValueError):
        try:
            return str(json.loads(ws_path(ws, "release-manifest.json").read_text(encoding="utf-8")).get("version") or "")
        except (OSError, ValueError):
            return ""


def kit_env(ws: str) -> dict:
    env = os.environ.copy()
    env["VIDEO_AUTOPILOT_ROOT"] = str(Path(ws).resolve())
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _popen(args: list[str], cwd: str, env: dict) -> subprocess.Popen:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=flags)


def run_streaming(args: list[str], cwd: str, env: dict, job: Job, markers: list[tuple[str, int]]) -> list[str]:
    """Run a process, feed its output to the job log and advance steps on marker text."""
    proc = _popen(args, cwd, env)
    lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        lines.append(line)
        job.line(line)
        for needle, step in markers:
            if needle in line:
                job.advance_to(step)
    proc.wait()
    if proc.returncode != 0:
        raise UserFacingError(explain_failure(lines))
    return lines


def explain_failure(lines: list[str]) -> str:
    """Turn a kit traceback into the messages a person can act on."""
    text = "\n".join(lines)
    gate = re.search(r"AssertionError: \[[^\]]*\] ([^\n]*):\n((?:  - [^\n]*\n?)+)", text)
    if gate:
        items = [friendly(x[4:]) for x in gate.group(2).splitlines() if x.startswith("  - ")]
        return "輸出前檢查沒有通過：\n" + "\n".join("• " + i for i in items)
    err = re.findall(r"^(\w+Error): (.*)$", text, re.M)
    if err:
        return friendly(err[-1][1]) or err[-1][0]
    tail = [ln for ln in lines if ln.strip()][-3:]
    return "處理失敗。" + (" 最後的訊息：" + " / ".join(tail) if tail else "")


# The kit's gate speaks to editors ("S-O 字幕中位停留 2.50s > 1.8s …"); say the same thing plainly.
_PLAIN = [
    (r"S-R 讀不完：'(.+)' (\d+) 字只停 ([\d.]+)s = ([\d.]+) 字/秒.*",
     lambda m: "「%s」讀不完：%s 個字只出現 %s 秒（每秒 %s 字，上限 7）。縮短這句，或拉長它所在的片段"
     % (m[1], m[2], m[3], m[4])),
    (r"S-R 偏快：'(.+)' ([\d.]+) 字/秒.*",
     lambda m: "「%s」稍快（每秒 %s 字），再短一點會更好讀" % (m[1], m[2])),
    (r"S-I 非白字比例 (\d+)% > 35%",
     lambda m: "金色字太多（佔 %s%%），上限 35%%。把部分字幕改回白色，或多加幾句白色字幕" % m[1]),
    (r"S-I 非白色數 (\d+) > 2 種.*", lambda m: "用了 %s 種顏色，最多 2 種" % m[1]),
    (r"S-A 缺「一句這是什麼」.*", lambda m: "開場缺一句介紹：請在開場或第 1 段加一句「這是什麼」"),
    (r"S-A 開場段沒有任何字幕.*", lambda m: "開場片段沒有字幕：第一句請寫地點名稱"),
    (r"S-A 首條字幕 '(.*)' 不含 place='(.*)'", lambda m: "第一句字幕「%s」沒有地點名稱「%s」" % (m[1], m[2])),
    (r"S-A 開場前兩段找不到 what='(.*)'.*",
     lambda m: "開場沒有出現「%s」這句介紹（不影響輸出）" % m[1]),
    (r"S-B 片長 ([\d.]+)s 不在 (\d+)-(\d+)s 帶.*",
     lambda m: "影片長度 %s 秒，IG Reels 要 %s–%s 秒。調整片段長度" % (m[1], m[2], m[3])),
    (r"S-C 首刀 ([\d.]+)s > 2\.0s.*", lambda m: "開場片段 %s 秒太長，請縮到 2 秒以內" % m[1]),
    (r"S-D loop 未對齊.*|S-D 末段未回首段 clip.*",
     lambda m: "最後一段要接回開場畫面才能無縫循環，請不要改動最後一段"),
    (r"S-D 末字幕距片尾 <([\d.]+)s.*", lambda m: "最後一句字幕離片尾太近，請移到前面的片段"),
    (r"S-G 有字幕綁在 loop 段.*", lambda m: "最後一段（循環）不能放字幕"),
    (r"S-O 字幕中位停留 ([\d.]+)s > ([\d.]+)s.*",
     lambda m: "字幕換得比較慢：每句平均停 %s 秒，熱門短片通常 1 秒多就換一句（不影響輸出）" % m[1]),
    (r"S-O 換句 ([\d.]+) 句/分 < (\d+).*",
     lambda m: "字幕偏少：每分鐘 %s 句，多加幾句會更有節奏（不影響輸出）" % m[1]),
    (r"S-Q 首幀銳利度.*", lambda m: "開場第一格畫面不夠清楚，可以換一段更清楚的開場（不影響輸出）"),
    (r"S-S (\S+) 字幕 (\d+) 字 > (\d+) 字.*", lambda m: "有一句特效字幕 %s 個字，特效字最多 %s 字" % (m[2], m[3])),
    (r"S-S 連續使用.*", lambda m: "連續好幾句用同一種字幕特效（不影響輸出）"),
    (r"S-A/E 缺 (\w+).*", lambda m: {"place": "缺地點名稱", "what": "缺一句介紹", "addr": "缺地址"}.get(m[1], m.group(0))),
    (r"素材不存在：(.*)", lambda m: "找不到素材檔案：%s。請重新分析素材" % m[1]),
]


def friendly(message: str) -> str:
    """Translate a kit gate message into plain language; fall back to dropping the rule code."""
    text = message.strip()
    for pattern, render in _PLAIN:
        m = re.fullmatch(pattern, text, re.S)
        if m:
            return render(m)
    return re.sub(r"^S-[A-Z](?:/[A-Z])*\s*", "", text)


# ---------------------------------------------------------------- plan files

def read_plan(plan_path: Path) -> tuple[dict, dict]:
    scope: dict = {"__file__": str(plan_path)}
    code = plan_path.read_text(encoding="utf-8")
    exec(compile(code, str(plan_path), "exec"), scope)  # plan files are written by the kit or by us
    return dict(scope.get("SPEC") or {}), dict(scope.get("COPY") or {})


def write_plan(plan_path: Path, spec: dict, copy: dict) -> None:
    body = [
        "# -*- coding: utf-8 -*-",
        '"""由 Reels 工作室產生。要修改請用 Reels 工作室，手動修改會在下次儲存時被覆蓋。"""',
        "",
        "SPEC = " + _py(spec),
        "",
        "COPY = " + _py(copy),
        "",
    ]
    tmp = plan_path.with_suffix(".tmp")
    tmp.write_text("\n".join(body), encoding="utf-8")
    os.replace(tmp, plan_path)


def _py(value) -> str:
    """repr() that keeps CJK readable and tuples as tuples."""
    if isinstance(value, dict):
        inner = ",\n".join("    %r: %s" % (k, _py(v).replace("\n", "\n    ")) for k, v in value.items())
        return "{\n" + inner + ",\n}" if value else "{}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[\n" + ",\n".join("    " + _py(v).replace("\n", "\n    ") for v in value) + ",\n]"
    if isinstance(value, tuple):
        return "(" + ", ".join(_py(v) for v in value) + ("," if len(value) == 1 else "") + ")"
    return repr(value)


# ---------------------------------------------------------------- gate

def gate_check(ws: str, spec: dict) -> dict:
    """Run the kit's own Shorts gate on a spec and return fails/warns/caption timings."""
    if not installed(ws):
        return {"ok": False, "fails": ["尚未安裝剪輯引擎（video-autopilot-kit）"], "warns": [], "caps": [], "dur": 0}
    proc = subprocess.run([sys.executable, str(HELPER), str(Path(ws).resolve())],
                          input=json.dumps(spec, ensure_ascii=False), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=kit_env(ws), timeout=120,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        rep = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "fails": ["無法執行檢查：" + (proc.stderr.strip().splitlines() or ["未知錯誤"])[-1]],
                "warns": [], "caps": [], "dur": 0}
    rep["fails"] = [friendly(x) for x in rep.get("fails", [])]
    rep["warns"] = [friendly(x) for x in rep.get("warns", [])]
    return rep
