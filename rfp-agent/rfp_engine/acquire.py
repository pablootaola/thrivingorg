"""Document acquisition: download, hash, count on disk, write 00_SOURCE.md.

Destination (Dropbox): <RFP Folder>/00_Active/<Buyer>-<SolicitationNo>-<Short-Scope>/
Buyer filenames are kept unchanged. A download is confirmed by a directory
listing and a hash, never by a portal status.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from . import http
from .model import MADRID, fmt_date

_SAFE = re.compile(r"[^A-Za-z0-9]+")


def folder_name(buyer: str, number: str, title: str, max_scope_words: int = 8) -> str:
    def part(s, n=None):
        words = [w for w in _SAFE.split(s or "") if w]
        return "-".join(words[:n] if n else words)
    buyer_p = part(re.sub(r"\b(City|County|Town|Village) of\b", r"\1", buyer or "", flags=re.I), 4)
    return "-".join(p for p in (buyer_p, part(number), part(title, max_scope_words)) if p)[:120]


def safe_filename(name: str) -> str:
    name = unquote(name or "").replace("/", "_").replace("\\", "_").strip()
    return name or "document"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class AcquisitionRecord:
    source: str
    solicitation_url: str
    folder: str
    listed: list[dict] = field(default_factory=list)  # {name, url}
    on_disk: list[dict] = field(default_factory=list)  # {name, bytes, sha256}
    missing: list[dict] = field(default_factory=list)  # {name, reason}
    acquired_at: datetime | None = None

    @property
    def fraction(self) -> str:
        return f"{len(self.on_disk)}/{len(self.listed)}"


def download_all(docs: list[dict], dest: Path, source: str, solicitation_url: str) -> AcquisitionRecord:
    dest.mkdir(parents=True, exist_ok=True)
    rec = AcquisitionRecord(source=source, solicitation_url=solicitation_url, folder=dest.name,
                            acquired_at=datetime.now(MADRID))
    for d in docs:
        rec.listed.append({"name": d.get("name", ""), "url": d.get("url", "")})
        if d.get("kind") == "link":
            rec.missing.append({"name": d.get("name", ""), "reason": f"external link, trace manually: {d.get('url')}"})
            continue
        if (d.get("access") or "public").lower() not in ("public", ""):
            rec.missing.append({"name": d.get("name", ""), "reason": f"access level {d.get('access')}: needs Pablo's session"})
            continue
        target = dest / safe_filename(d.get("name", ""))
        try:
            r = http.get(d["url"], stream=True, timeout=180, allow_redirects=True)
            if r.status_code != 200:
                rec.missing.append({"name": d.get("name", ""), "reason": f"HTTP {r.status_code}"})
                continue
            with open(target, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        except Exception as e:
            rec.missing.append({"name": d.get("name", ""), "reason": f"download error: {e}"})
    # Count what is actually on disk. This, not the loop above, is the evidence.
    listed_names = {safe_filename(x["name"]) for x in rec.listed}
    for p in sorted(dest.iterdir()):
        if p.is_file() and p.name in listed_names and p.stat().st_size > 0:
            rec.on_disk.append({"name": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)})
    got = {x["name"] for x in rec.on_disk}
    for x in rec.listed:
        n = safe_filename(x["name"])
        if n not in got and not any(m["name"] == x["name"] for m in rec.missing):
            rec.missing.append({"name": x["name"], "reason": "not found on disk after download"})
    return rec


def source_md(rec: AcquisitionRecord, *, title: str, buyer: str, number: str, due: str) -> str:
    lines = [
        "# 00_SOURCE", "",
        f"- Opportunity: {title}",
        f"- Buyer: {buyer}",
        f"- Solicitation number: {number or 'not published'}",
        f"- Deadline: {due or 'not established'}",
        f"- Source: {rec.source}",
        f"- Solicitation URL: {rec.solicitation_url}",
        f"- Acquired: {fmt_date(rec.acquired_at, MADRID) if rec.acquired_at else ''}",
        f"- Acquisition fraction (files on disk / files listed): {rec.fraction}",
        "",
        "## Files on disk", "",
        "| File | Bytes | SHA-256 |", "|---|---|---|",
    ]
    lines += [f"| {f['name']} | {f['bytes']} | {f['sha256']} |" for f in rec.on_disk]
    lines += ["", "## Files not obtained", ""]
    lines += [f"- {m['name']}: {m['reason']}" for m in rec.missing] or ["- none"]
    lines += ["", "Confirmed by directory listing and hash, not by a portal status.", ""]
    return "\n".join(lines)


def write_source_md(rec: AcquisitionRecord, dest: Path, **kw) -> Path:
    p = dest / "00_SOURCE.md"
    p.write_text(source_md(rec, **kw), encoding="utf-8")
    return p
