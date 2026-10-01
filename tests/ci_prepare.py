"""CI helper: install the kit, media packages and caption font through Reels Studio's own installers.

Exercises the same code paths the 環境檢查 page uses, then prints the environment status.
Usage: python tests/ci_prepare.py <workspace>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reels_studio import env  # noqa: E402
from reels_studio.jobs import Job  # noqa: E402

ws = str(Path(sys.argv[1]).resolve())
for item in ("kit", "media", "wenkai"):
    job = Job("install:" + item, item, ["install"])
    env.install(item, ws, job)
    print("installed", item)
    if item == "media":
        print("\n".join(job.log[-15:]))

items = env.status(ws)
status = {i["id"]: i["ok"] for i in items}
print(status)
for i in items:
    if i.get("detail"):
        print(i["id"], "detail:", i["detail"])
missing = [k for k in ("python", "ffmpeg", "media", "kit", "wenkai") if not status[k]]
if missing:
    raise SystemExit("still missing: %s" % missing)
