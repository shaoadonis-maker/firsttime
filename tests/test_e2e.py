"""End-to-end: drive the HTTP API through a full Reels export on synthetic footage.

Needs ffmpeg and a kit workspace. Point REELS_TEST_WORKSPACE at a folder where
video-autopilot-kit is installed (the test installs nothing itself):

    REELS_TEST_WORKSPACE=/path/to/ws python -m pytest tests/test_e2e.py -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

WS = os.path.abspath(os.environ["REELS_TEST_WORKSPACE"]) if os.environ.get("REELS_TEST_WORKSPACE") else ""
pytestmark = pytest.mark.skipif(not (WS and shutil.which("ffmpeg")),
                                reason="needs REELS_TEST_WORKSPACE with the kit installed and ffmpeg")


@pytest.fixture(scope="module")
def api():
    home = tempfile.mkdtemp()
    os.environ["REELS_STUDIO_HOME"] = home
    import importlib
    from reels_studio import config
    importlib.reload(config)
    from reels_studio import server
    importlib.reload(server)
    config.update({"workspace": WS, "setup_done": True})
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def call(method, path, body=None, raw=None, token=True, expect=200):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(base + path, data=data, method=method)
        if token:
            req.add_header("X-Studio-Token", server.TOKEN)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                status, payload, headers = resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as err:
            status, payload, headers = err.code, err.read(), err.headers
        assert status == expect, (status, payload[:500])
        if headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(payload)
        return payload

    yield call
    srv.shutdown()


def wait_job(call, job):
    for _ in range(600):
        job = call("GET", "/api/jobs/" + job["id"])
        if job["state"] != "running":
            return job
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def make_clips(tmp: Path) -> list[Path]:
    clips = []
    for i in range(4):
        out = tmp / ("旅遊片段%d.mov" % i)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=1080x1920:rate=30,hue=h=%d" % (i * 70), "-f", "lavfi", "-i",
                        "sine=frequency=%d" % (300 + i * 100), "-t", "6", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
        clips.append(out)
    return clips


def test_rejects_requests_without_token(api):
    api("POST", "/api/projects", {"title": "x"}, token=False, expect=403)


def test_full_reels_export(api, tmp_path):
    bgm = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=30",
                    str(bgm)], check=True)
    lib = api("PUT", "/api/bgm?folder=%E6%B8%AC%E8%A9%A6&name=tone.mp3", raw=bgm.read_bytes())
    assert any(f["folder"] == "測試" and "tone.mp3" in f["tracks"] for f in lib["folders"])

    p = api("POST", "/api/projects", {"title": "名古屋城", "what": "全家第一次來", "addr": "愛知縣名古屋市中區本丸1-1"})
    for clip in make_clips(tmp_path):
        p = api("PUT", "/api/projects/%s/clips?name=%s" % (p["id"], urllib.request.quote(clip.name)),
                raw=clip.read_bytes())
    assert len(p["clips"]) == 4 and p["clips"][0]["original"] == "旅遊片段0.mov"
    api("PUT", "/api/projects/%s/clips?name=notes.txt" % p["id"], raw=b"hello", expect=400)

    job = wait_job(api, api("POST", "/api/projects/%s/scan" % p["id"]))
    assert job["state"] == "done", job
    p = api("GET", "/api/projects/" + p["id"])
    assert p["status"] == "draft" and len(p["segs"]) >= 3
    assert api("GET", "/api/projects/%s/thumb/0" % p["id"])[:2] == b"\xff\xd8"

    # A caption too long to read in time must be blocked by the kit's own gate.
    caps = [{"seg": 0, "text": "名古屋城", "color": "white"},
            {"seg": 0, "text": "全家人第一次一起來到這裡", "color": "white"}]
    api("POST", "/api/projects/" + p["id"], {"caps": caps, "bgm_folder": "測試"})
    rep = api("POST", "/api/projects/%s/check" % p["id"])
    assert not rep["ok"] and any("讀不完" in f for f in rep["fails"]), rep
    failed = wait_job(api, api("POST", "/api/projects/%s/build" % p["id"]))
    assert failed["state"] == "failed" and "讀不完" in failed["error"], failed

    # Gold is for one or two highlights: half the characters in gold is rejected.
    caps = [{"seg": 0, "text": "名古屋城", "color": "gold"}, {"seg": 1, "text": "第一次來", "color": "white"}]
    api("POST", "/api/projects/" + p["id"], {"caps": caps})
    rep = api("POST", "/api/projects/%s/check" % p["id"])
    assert not rep["ok"] and any("金色字太多" in f for f in rep["fails"]), rep

    caps = [{"seg": 0, "text": "名古屋城", "color": "gold"}, {"seg": 1, "text": "先逛本丸御殿", "color": "white"},
            {"seg": 2, "text": "小孩最愛金鯱", "color": "white"}]
    api("POST", "/api/projects/" + p["id"], {"caps": caps})
    rep = api("POST", "/api/projects/%s/check" % p["id"])
    assert rep["ok"], rep
    assert [c["text"] for c in rep["caps"] if c["kind"] != "chip"][:2] == ["名古屋城", "先逛本丸御殿"]

    job = wait_job(api, api("POST", "/api/projects/%s/build" % p["id"]))
    assert job["state"] == "done", job["error"] + "\n" + "\n".join(job["log"][-20:])
    p = api("GET", "/api/projects/" + p["id"])
    assert p["status"] == "review" and p["has_output"] and p["copy"]

    head = api("GET", "/api/projects/%s/video" % p["id"])
    assert head[4:8] == b"ftyp"
    qa = api("GET", "/api/projects/%s/qa" % p["id"])
    assert qa["score"] and qa["dims"]
    assert api("POST", "/api/projects/%s/approve" % p["id"])["status"] == "done"
    assert any(x["id"] == p["id"] for x in api("GET", "/api/projects")["projects"])
