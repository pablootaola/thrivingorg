"""Build faces.json (private, never committed) from a folder of headshots.

  python proposal/faces_from_folder.py PHOTO_DIR roster.json faces.json

roster.json maps a face key to the person's display name, role, and the photo file:
  {"<key>": {"name": "...", "role": "...", "file": "<Name> - Profile Photo.jpg"}}

Every photo is centre-cropped to a square and re-encoded at 400 px so all faces
share the same treatment, then stored as a data URI so no build waits on a folder.
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path


def encode(path: Path, size: int = 400) -> str:
    try:
        from PIL import Image
    except ImportError:  # fall back to the original bytes
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, max(0, (h - s) // 3), (w - s) // 2 + s, max(0, (h - s) // 3) + s)).resize((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main(photo_dir: str, roster: str, out: str) -> int:
    d = Path(photo_dir)
    r = json.loads(Path(roster).read_text())
    faces, missing = {}, []
    for key, p in r.items():
        f = d / p["file"]
        if not f.exists():
            missing.append(f"{key}: {f.name}")
            continue
        faces[key.lower()] = {"name": p["name"], "role": p["role"], "photo": encode(f)}
    Path(out).write_text(json.dumps(faces), encoding="utf-8")
    print(f"{len(faces)}/{len(r)} faces encoded")
    for m in missing:
        print("missing", m)
    return 0 if not missing else 3


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
