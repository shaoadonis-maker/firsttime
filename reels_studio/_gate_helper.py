"""Runs inside a kit workspace: read a spec (JSON on stdin), print the gate report as JSON.

Kept as a separate process so the kit's modules never load into the GUI server.
"""
import io
import json
import sys
from contextlib import redirect_stdout

root = sys.argv[1]
sys.path[:0] = [root + "/src", root + "/src/longform_maker"]

spec = json.loads(sys.stdin.read())
spec["segs"] = [tuple(s) for s in spec.get("segs", [])]
spec["caps_by_seg"] = [(c[0], [tuple(p) for p in c[1]], c[2]) for c in spec.get("caps_by_seg", [])]

with redirect_stdout(io.StringIO()):
    from shorts_gate import gate_shorts  # noqa: E402
    ok, rep = gate_shorts(spec)

caps = []
for cap in rep.get("caps") or []:
    start, end, pieces, kind = cap[0], cap[1], cap[2], cap[3]
    caps.append({"start": start, "end": end, "kind": kind,
                 "text": "".join(str(p[0]) for p in pieces)})
print(json.dumps({"ok": bool(ok), "fails": list(rep.get("fails") or []), "warns": list(rep.get("warns") or []),
                  "caps": caps, "dur": rep.get("dur") or 0}, ensure_ascii=False, default=str))
